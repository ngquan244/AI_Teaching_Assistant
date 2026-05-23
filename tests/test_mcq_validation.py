"""
Tests for MCQ structural validation (P0 + P0.5 softening).

P0 covered banned aggregator phrases, combined-answer options, and a passing
baseline. P0.5 softens the validator so that:
  - Single Vietnamese tokens ("tất cả", "cả hai", "đều đúng") are NOT enough
    to reject; only explicit multi-word meta phrases trigger.
  - Length bias is a warning, not a hard reject.
  - Combined-superset requires an explicit connector token.
"""

import pytest

from backend.modules.document_rag.quiz_generator import validate_mcq_structure


# ---- Helpers ---------------------------------------------------------------

def _q(options, correct_index=0, question="Câu hỏi mẫu?"):
    return question, options, correct_index


# ---- Banned aggregator phrases ---------------------------------------------

@pytest.mark.parametrize("bad_option", [
    "All of the above",
    "all of the above.",
    "ALL of these",
    "All answers are correct",
    "Tất cả các đáp án trên",
    "Tất cả đáp án trên",
    "Cả 3 đáp án trên",
    "Cả ba đáp án trên",
    "Các ý trên đều đúng",
])
def test_rejects_all_of_above(bad_option):
    q, opts, ci = _q(["Distractor A", "Distractor B", "Correct fact", bad_option], correct_index=3)
    ok, reason = validate_mcq_structure(q, opts, ci)
    assert ok is False
    assert reason == "all_of_above"


@pytest.mark.parametrize("bad_option", [
    "None of the above",
    "None of these",
    "No correct answer",
    "Không có đáp án nào đúng",
    "Không đáp án nào đúng",
    "Không có ý nào đúng",
])
def test_rejects_none_of_above(bad_option):
    q, opts, ci = _q(["Fact A", "Fact B", "Fact C", bad_option], correct_index=0)
    ok, reason = validate_mcq_structure(q, opts, ci)
    assert ok is False
    assert reason == "none_of_above"


# ---- P0.5: bare single tokens MUST NOT trigger rejection -------------------

@pytest.mark.parametrize("benign_option", [
    "Tất cả sinh viên phải đăng ký tín chỉ đúng hạn",  # contains "tất cả" + "đúng"
    "Cả hai phiên bản đều hỗ trợ thanh toán qua ông",  # contains "cả hai" + "đều"
    "Cả ba lớp tham gia buổi thực hành ở phòng A",        # contains "cả ba"
    "Đáp án này đều đúng trong mọi trường hợp thực tế",  # contains "đều đúng" but not as meta
    "All employees must complete onboarding within two weeks",  # bare "all"
    "Both interfaces support voice input as a fallback",        # bare "both"
])
def test_does_not_reject_bare_aggregator_tokens(benign_option):
    options = [
        benign_option,
        "Một lựa chọn khác với nội dung trung lập hằng ngày",
        "Lựa chọn phân biệt rõ ràng với từng đáp án còn lại",
        "Một lựa chọn độc lập và hiển nhiên không đúng",
    ]
    ok, reason = validate_mcq_structure("Câu hỏi?", options, correct_index=0)
    assert ok is True, f"Expected pass for benign option {benign_option!r}, got reason={reason!r}"


# ---- Combined / cumulative answers -----------------------------------------

@pytest.mark.parametrize("bad_option", [
    "Both A and B",
    "A and B only",
    "A and C",
    "B and C",
    "A, B and C",
    "Cả A và B",
    "Cả A và C",
    "A và C",
    "B và D",
    "Đáp án A và C",
    "Phương án A và B",
    "Options A and C",
])
def test_rejects_combined_answer(bad_option):
    q, opts, ci = _q(["Fact A", "Fact B", "Fact C", bad_option], correct_index=0)
    ok, reason = validate_mcq_structure(q, opts, ci)
    assert ok is False
    assert reason == "combined_answer"


# ---- Suspicious meta phrases (multi-word only) -----------------------------

def test_rejects_suspicious_meta_phrase():
    q, opts, ci = _q(
        ["Fact one", "Fact two", "Fact three", "Tất cả các ý trên"],
        correct_index=0,
    )
    ok, reason = validate_mcq_structure(q, opts, ci)
    assert ok is False
    # "tat ca cac y tren" is an explicit multi-word meta phrase.
    assert reason in {"suspicious_meta_option", "all_of_above"}


# ---- Combined superset (semantic merge of other options) -------------------

def test_rejects_correct_option_that_is_superset_of_distractors_with_connector():
    options = [
        "Recognition based menu interaction",        # short distractor 1
        "Recall based command interaction",          # short distractor 2
        "Voice based natural language interaction",  # short distractor 3
        # Correct option merges all the above keywords AND uses a connector.
        "Recognition based menu interaction and recall based command interaction "
        "and voice based natural language interaction combined",
    ]
    ok, reason = validate_mcq_structure("Câu hỏi?", options, correct_index=3)
    assert ok is False
    assert reason in {"combined_answer", "semantic_duplicate_option"}


def test_does_not_reject_long_correct_option_without_connector():
    # P0.5: a legitimately detailed correct option without an aggregator
    # connector must NOT be treated as a combined-superset answer.
    options = [
        "Slip",
        "Mistake",
        "Lapse",
        "An interaction error that occurs when the user formulates the wrong "
        "intention because of an incorrect mental model of the system, often "
        "leading to systematic problems requiring redesign of the conceptual model.",
    ]
    ok, reason = validate_mcq_structure(
        "Đâu là định nghĩa của mistake?", options, correct_index=3,
    )
    assert ok is True, f"Expected pass; got reason={reason!r}"


# ---- Semantic / lexical duplicate options ----------------------------------

def test_rejects_near_duplicate_options():
    options = [
        "The gap between user goals and system actions available",
        "The gap between user goals and system actions available now",
        "Gulf of evaluation is the gap between system state and user understanding",
        "Ergonomics studies physical interaction with devices",
    ]
    ok, reason = validate_mcq_structure("Định nghĩa nào đúng?", options, correct_index=0)
    assert ok is False
    assert reason == "semantic_duplicate_option"


# ---- Invalid input shape ---------------------------------------------------

@pytest.mark.parametrize("opts,ci", [
    (["A", "B", "C"], 0),                    # not 4 options
    (["A", "B", "C", "D", "E"], 0),          # too many
    (["A", "B", "C", ""], 0),                # empty option
    (["A", "B", "C", "D"], None),            # no correct index
    (["A", "B", "C", "D"], 7),               # out of range
])
def test_rejects_malformed_input(opts, ci):
    ok, reason = validate_mcq_structure("Q?", opts, ci)
    assert ok is False
    assert reason == "invalid_mcq_structure"


# ---- Baseline: 4 normal options must pass ----------------------------------

def test_accepts_clean_mcq():
    options = [
        "Khoảng cách giữa mục tiêu của người dùng và hành động hệ thống cho phép",
        "Khoảng cách giữa trạng thái hệ thống và hiểu biết của người dùng",
        "Sự khác biệt giữa thiết kế bằng menu và bằng dòng lệnh",
        "Mức độ hấp dẫn về mặt thẩm mỹ của giao diện",
    ]
    ok, reason = validate_mcq_structure(
        "Gulf of execution là gì trong tương tác người-máy?",
        options,
        correct_index=0,
    )
    assert ok is True
    assert reason == ""


def test_accepts_clean_english_mcq():
    options = [
        "A user error caused by carrying out the right intention incorrectly",
        "A user error caused by forming the wrong intention",
        "A hardware failure of the input device",
        "A latency issue in the system response time",
    ]
    ok, reason = validate_mcq_structure(
        "Which best describes a slip in HCI?",
        options,
        correct_index=0,
    )
    assert ok is True
    assert reason == ""
