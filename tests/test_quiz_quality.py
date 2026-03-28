import os
from collections import Counter
from types import MethodType, SimpleNamespace

from langchain_core.documents import Document

os.environ["DEBUG"] = "false"

from backend.modules.document_rag.llm_providers import BaseLLM
from backend.modules.document_rag.quiz_generator import QuizGenerator
from backend.modules.document_rag.retriever import MultiCollectionRetriever


class _StubChatModel:
    def __call__(self, _prompt):
        return self.invoke(_prompt)

    def invoke(self, _prompt):
        return SimpleNamespace(content="{}")


class _LengthLimitChatModel:
    def __call__(self, _prompt):
        return self.invoke(_prompt)

    def invoke(self, _prompt):
        raise RuntimeError("Could not parse response content as the length limit was reached")


class _StubLLM(BaseLLM):
    @property
    def provider_name(self) -> str:
        return "stub"

    def _create_llm(self, json_mode: bool = False, max_tokens=None):
        return _StubChatModel()

    def check_connection(self):
        return {"connected": True}


class _LengthLimitLLM(_StubLLM):
    def _create_llm(self, json_mode: bool = False, max_tokens=None):
        return _LengthLimitChatModel()


class _DummyRetriever:
    def extract_citations(self, documents):
        return []

    def format_context(self, documents):
        return "\n".join(doc.page_content for doc in documents)


class _FakeRegistry:
    def __init__(self, metas):
        self._metas = metas

    def reload(self):
        return None

    def get_all(self, user_id=None):
        return self._metas


class _FakeCollectionManager:
    def __init__(self, docs_by_hash):
        self._docs_by_hash = docs_by_hash
        self.registry = _FakeRegistry(
            [
                SimpleNamespace(file_hash=file_hash, filename=f"{file_hash}.pdf")
                for file_hash in docs_by_hash
            ]
        )

    def query_collection(self, file_hash, query, k, **kwargs):
        return self._docs_by_hash[file_hash][:k]


def _make_docs(file_hash: str, count: int):
    return [
        Document(
            page_content=f"{file_hash} content block {index}",
            metadata={
                "file_hash": file_hash,
                "source": f"{file_hash}.pdf",
                "page": index,
            },
        )
        for index in range(count)
    ]


def test_round_robin_budget_spreads_across_multiple_collections():
    manager = _FakeCollectionManager(
        {
            "a": _make_docs("a", 6),
            "b": _make_docs("b", 6),
            "c": _make_docs("c", 6),
        }
    )
    retriever = MultiCollectionRetriever(manager)

    docs = retriever.retrieve_with_budget(
        query="topic",
        max_total_docs=7,
        target_file_hashes=["a", "b", "c"],
    )

    counts = Counter(doc.metadata["file_hash"] for doc in docs)
    assert len(docs) == 7
    assert counts == {"a": 3, "b": 2, "c": 2}


def test_round_robin_budget_does_not_cap_single_collection():
    manager = _FakeCollectionManager({"solo": _make_docs("solo", 10)})
    retriever = MultiCollectionRetriever(manager)

    docs = retriever.retrieve_with_budget(
        query="topic",
        max_total_docs=8,
        target_file_hashes=["solo"],
    )

    assert len(docs) == 8
    assert {doc.metadata["file_hash"] for doc in docs} == {"solo"}


def test_format_quiz_accepts_correct_index_and_remaps_after_shuffle():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    formatted = generator._format_quiz(
        [
            {
                "question": "Which option is correct?",
                "options": ["Alpha", "Beta", "Gamma", "Delta"],
                "correct_index": 2,
            }
        ]
    )

    assert len(formatted) == 1
    question = formatted[0]
    assert set(question["options"].values()) == {"Alpha", "Beta", "Gamma", "Delta"}
    assert question["options"][question["correct_answer"]] == "Gamma"
    assert "explanation" not in question


def test_format_quiz_rejects_invalid_option_sets_without_padding():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    formatted = generator._format_quiz(
        [
            {
                "question": "Invalid question",
                "options": ["Only A", "Only B", "Only C"],
                "correct_answer": "A",
            }
        ]
    )

    assert formatted == []


def test_plan_batch_sizes_supports_exact_count_rollout():
    assert QuizGenerator._plan_batch_sizes(12) == [12]
    assert QuizGenerator._plan_batch_sizes(20) == [10, 10]
    assert QuizGenerator._plan_batch_sizes(30) == [15, 15]
    assert QuizGenerator._plan_batch_sizes(31) == [11, 10, 10]
    assert QuizGenerator._plan_batch_sizes(50) == [13, 13, 12, 12]


def test_existing_questions_prompt_is_capped_to_recent_budget():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    questions = [{"question": f"Question {index} about embeddings and context windows"} for index in range(1, 26)]
    prompt_text = generator._format_existing_questions_for_prompt(questions, max_items=5, max_chars=180)

    assert "Question 1" not in prompt_text
    assert "Question 25" in prompt_text
    assert "omitted for prompt budget" in prompt_text


def test_should_use_blueprint_only_for_large_or_multi_topic_cases():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    assert generator._should_use_blueprint(10, ["Word2Vec"], raw_document_count=8, final_budget=12) is False
    assert generator._should_use_blueprint(20, ["Word2Vec"], raw_document_count=8, final_budget=12) is True
    assert generator._should_use_blueprint(10, ["Word2Vec", "CBOW"], raw_document_count=8, final_budget=12) is True
    assert generator._should_use_blueprint(40, ["Word2Vec"], raw_document_count=30, final_budget=12) is False
    assert generator._should_use_blueprint(20, [f"Topic {index}" for index in range(8)], raw_document_count=30, final_budget=12) is False


def test_build_blueprint_degrades_to_local_planner_on_length_limit():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_LengthLimitLLM(model="stub"))

    blueprint, failure_reason = generator._build_blueprint(
        context="Word2Vec and CBOW context",
        topic="Word2Vec",
        difficulty="medium",
        language="vi",
        num_questions=20,
    )

    assert failure_reason == "length_limit"
    assert len(blueprint["slots"]) == 20


def test_second_refill_threshold_is_conditional():
    assert QuizGenerator._should_run_second_refill(50, 8) is True
    assert QuizGenerator._should_run_second_refill(50, 9) is False
    assert QuizGenerator._should_run_second_refill(50, 10) is False
    assert QuizGenerator._should_run_second_refill(50, 11) is False
    assert QuizGenerator._should_run_second_refill(20, 4) is True
    assert QuizGenerator._should_run_second_refill(20, 5) is False


def test_partial_success_threshold_uses_95_percent_rule():
    assert QuizGenerator._partial_success_threshold(50) == 48
    assert QuizGenerator._partial_success_threshold(30) == 29
    assert QuizGenerator._partial_success_threshold(20) == 19
    assert QuizGenerator._partial_success_threshold(10) == 10


def test_partial_success_classification_matches_near_complete_policy():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    assert generator._is_partial_success(50, 48) is True
    assert generator._is_partial_success(50, 47) is False
    assert generator._is_partial_success(30, 29) is True
    assert generator._is_partial_success(20, 19) is True
    assert generator._is_partial_success(10, 9) is False


def test_shortfall_message_prioritizes_budget_and_large_request_reasons():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    message = generator._build_user_facing_shortfall_message(
        num_questions=50,
        final_count=48,
        blueprint_skip_reason="blueprint skipped due to large request",
        remaining_slots=[{"slot_id": "S49"}, {"slot_id": "S50"}],
        plan_stats={"budget_cap_hit": True},
    )

    assert "Đã tạo 48/50 câu hỏi, thiếu 2 câu." in message
    assert "chi phí an toàn" in message
    assert "tiết kiệm token" in message


def test_shortfall_message_uses_remaining_slot_reason_for_thin_context():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    message = generator._build_user_facing_shortfall_message(
        num_questions=20,
        final_count=19,
        blueprint_skip_reason=None,
        remaining_slots=[{"slot_id": "S20"}],
        plan_stats={"budget_cap_hit": False},
    )

    assert "Đã tạo 19/20 câu hỏi, thiếu 1 câu." in message
    assert "chưa đủ phủ hết mọi góc hỏi cần thiết" in message


def test_execute_exact_count_plan_uses_global_refill_1_and_conditional_refill_2_for_large_requests():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))
    blueprint = generator._normalize_blueprint({}, topic="Word2Vec, CBOW", num_questions=50)
    raw_documents = _make_docs("solo", 20)

    batch_retry_flags = []
    refill_modes = []

    def _make_question(slot):
        return {
            "slot_id": slot["slot_id"],
            "topic_group": slot.get("topic_group"),
            "topic_group_label": slot.get("topic_group_label"),
            "coverage_item": slot.get("coverage_item"),
            "support_level": slot.get("support_level"),
            "question_form": slot.get("question_form"),
            "trap_type": slot.get("trap_type"),
            "question": f"Question for {slot['slot_id']}",
            "options": {"A": "Alpha", "B": "Beta", "C": "Gamma", "D": "Delta"},
            "correct_answer": "A",
        }

    def fake_run_batch_generation(self, **kwargs):
        batch_retry_flags.append(kwargs["enable_retry"])
        batch_slots = kwargs["batch_slots"]
        accepted_slots = batch_slots[:-1]
        questions = [_make_question(slot) for slot in accepted_slots]
        missing = batch_slots[-1:]
        return questions, missing, {
            "malformed_count": len(missing),
            "retry_count": 0,
            "call_count": 1,
            "estimated_completion_tokens": 1000,
        }

    def fake_run_targeted_refill(self, **kwargs):
        refill_modes.append((kwargs["generation_mode"], kwargs["support_level_override"], len(kwargs["missing_slots"])))
        missing_slots = kwargs["missing_slots"]
        if kwargs["generation_mode"] == "global_refill_1":
            accepted = [_make_question(slot) for slot in missing_slots[:1]]
            remaining = missing_slots[1:]
        else:
            accepted = [_make_question(slot) for slot in missing_slots]
            remaining = []
        return accepted, remaining, {
            "malformed_count": len(remaining),
            "retry_count": 1,
            "call_count": 1,
            "estimated_completion_tokens": 900,
        }

    generator._run_batch_generation = MethodType(fake_run_batch_generation, generator)
    generator._run_targeted_refill = MethodType(fake_run_targeted_refill, generator)

    result = generator._execute_exact_count_plan(
        raw_documents=raw_documents,
        blueprint=blueprint,
        topic="Word2Vec, CBOW",
        difficulty="medium",
        language="vi",
        num_questions=50,
        cost_protected=True,
        blueprint_attempted=False,
    )

    assert batch_retry_flags == [False, False, False, False]
    assert refill_modes == [
        ("global_refill_1", None, 4),
        ("global_refill_2", "adjacent_in_scope", 3),
    ]
    assert len(result["questions"]) == 50
    assert result["stats"]["refill_count"] == 2
    assert result["stats"]["actual_calls"] == 6
    assert result["stats"]["budget_cap_hit"] is False


def test_normalize_blueprint_fills_missing_slots_and_keeps_supported_levels():
    generator = QuizGenerator(retriever=_DummyRetriever(), llm_provider=_StubLLM(model="stub"))

    blueprint = generator._normalize_blueprint(
        blueprint={
            "topic_groups": [
                {
                    "group_id": "G1",
                    "label": "Word embeddings",
                    "source_topics": ["Word2Vec", "Word Embedding"],
                    "evidence_refs": ["Document 1"],
                }
            ],
            "slots": [
                {
                    "slot_id": "ignored",
                    "topic_group": "G1",
                    "coverage_item": "CBOW objective",
                    "support_level": "direct_source",
                    "question_form": "definition",
                    "trap_type": "near_miss",
                    "evidence_refs": ["Document 2"],
                }
            ],
        },
        topic="Word2Vec, Word Embedding",
        num_questions=4,
    )

    assert len(blueprint["slots"]) == 4
    assert {slot["support_level"] for slot in blueprint["slots"]}.issubset({"direct_source", "close_inference"})
    assert all(slot["slot_id"].startswith("S") for slot in blueprint["slots"])
