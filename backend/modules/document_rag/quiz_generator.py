"""
Quiz Generator Module
=====================
Generate quiz questions from documents using RAG + configurable LLM backends.
Supports Groq Cloud (API) with strict JSON output.
"""

import json
import hashlib
import logging
import math
import random
import re
import time
import xml.etree.ElementTree as ET
from collections import Counter
from xml.dom import minidom
from typing import List, Dict, Any, Optional, Iterable, Tuple
from datetime import datetime

from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from .config import rag_config
from .document_payload import (
    extract_document_citations,
    format_context_documents,
)
from .retriever import DocumentRetriever
from .llm_providers import BaseLLM, LLMFactory
from backend.core.logger import quiz_logger

logger = logging.getLogger(__name__)


# ===== Quiz Data Models =====

class QuizQuestion(BaseModel):
    """Model for a single quiz question"""
    question: str = Field(description="Nội dung câu hỏi")
    options: List[str] = Field(description="Danh sách 4 đáp án A, B, C, D")
    correct_answer: str = Field(description="Đáp án đúng (A, B, C hoặc D)")
    explanation: str = Field(description="Giải thích ngắn gọn tại sao đáp án đúng")


class QuizOutput(BaseModel):
    """Model for quiz generation output"""
    quiz: List[QuizQuestion] = Field(default=[], description="Danh sách câu hỏi")
    message: str = Field(default="", description="Thông báo nếu có lỗi")


# ===== Prompt Template =====

QUIZ_GENERATION_PROMPT = """Bạn là một giáo viên chuyên nghiệp trong việc soạn đề thi trắc nghiệm chất lượng cao.

NHIỆM VỤ: Tạo CHÍNH XÁC {num_questions} câu hỏi trắc nghiệm dựa trên nội dung tài liệu được cung cấp.

NỘI DUNG TÀI LIỆU (CONTEXT):
{context}

CHỦ ĐỀ/YÊU CẦU: {topic}

ĐỘ KHÓ: {difficulty} (easy/medium/hard)

QUY TẮC BẮT BUỘC:
1. CHỈ sử dụng thông tin có trong Context để tạo câu hỏi
2. KHÔNG bịa đặt hoặc thêm kiến thức ngoài tài liệu
3. Mỗi câu hỏi PHẢI có đúng 4 đáp án: A, B, C, D
4. Các đáp án sai phải hợp lý, không quá dễ loại trừ
5. Câu hỏi phải rõ ràng, không mơ hồ
6. Tuân thủ độ khó yêu cầu:
   - easy: Câu hỏi đơn giản, kiểm tra ghi nhớ cơ bản
   - medium: Câu hỏi yêu cầu hiểu và áp dụng kiến thức
   - hard: Câu hỏi phân tích, so sánh, tổng hợp thông tin
7. BẮT BUỘC tạo CHÍNH XÁC {num_questions} câu. Đếm lại số câu trước khi trả về.

GUARDRAIL CHẤT LƯỢNG:
- Mỗi câu phải bám vào ít nhất 1 chi tiết/khái niệm CỤ THỂ trong context
- KHÔNG được lặp lại cùng một ý/khái niệm quá 2 câu
- Đa dạng hóa dạng câu hỏi: định nghĩa, ví dụ, so sánh, ứng dụng, ngoại lệ, quan hệ nhân quả
- Nếu một chủ đề đã hết ý, khai thác khía cạnh khác của context
- Đáp án đúng phải chính xác theo tài liệu
- Giải thích ngắn gọn (1-2 câu), trích dẫn từ context nếu có thể

XỬ LÝ TRƯỜNG HỢP ĐẶC BIỆT:
- Nếu Context KHÔNG chứa thông tin về "{topic}": trả về quiz rỗng với message giải thích
- Nếu Context quá ít để tạo đủ {num_questions} câu KHÁC NHAU: tạo tối đa số câu có thể, KHÔNG tạo câu rác/lặp

ĐỊNH DẠNG OUTPUT (JSON):
{{
  "quiz": [
    {{
      "question": "Nội dung câu hỏi?",
      "options": ["Đáp án A", "Đáp án B", "Đáp án C", "Đáp án D"],
      "correct_answer": "A",
      "explanation": "Giải thích ngắn gọn"
    }}
  ],
  "message": ""
}}

CHÚ Ý: Chỉ trả về JSON, không thêm text khác. Đảm bảo JSON hợp lệ."""


QUIZ_GENERATION_PROMPT_V2 = """You are an expert quiz creator. Create EXACTLY {num_questions} multiple-choice questions based ONLY on the provided document content.

DOCUMENT CONTENT:
{context}

TOPIC/REQUIREMENT: {topic}

DIFFICULTY LEVEL: {difficulty} (easy/medium/hard)

STRICT RULES:
1. Questions MUST be based ONLY on the provided content - DO NOT make up information
2. Each question has exactly 4 options: A, B, C, D
3. Wrong answers should be plausible but clearly incorrect based on the document
4. Follow the difficulty level:
   - easy: Simple recall questions testing basic facts
   - medium: Questions requiring understanding and application
   - hard: Complex questions requiring analysis and synthesis
5. Questions should test understanding, not just memorization
6. You MUST create EXACTLY {num_questions} questions. Count them before returning.

QUALITY GUARDRAILS:
- Each question must reference at least 1 specific detail/concept from the content
- Do NOT repeat the same concept/idea in more than 2 questions
- Diversify question types: definition, example, comparison, application, exception, cause-effect
- If one topic area is exhausted, explore different aspects of the content
- Keep explanations brief (1-2 sentences)
- If content is truly insufficient for {num_questions} UNIQUE questions, create the maximum possible WITHOUT creating filler/duplicate questions

OUTPUT FORMAT (JSON only, no markdown):
{{
  "quiz": [
    {{
      "question": "Question text here?",
      "options": ["Option A text", "Option B text", "Option C text", "Option D text"],
      "correct_answer": "A",
      "explanation": "Brief explanation why this is correct"
    }}
  ],
  "message": ""
}}

If the topic is not found in the document, return:
{{"quiz": [], "message": "Không tìm thấy nội dung về '{topic}' trong tài liệu"}}

Return ONLY valid JSON, no additional text."""


# ===== Supplement Prompt Templates (for retry when missing questions) =====

QUIZ_SUPPLEMENT_PROMPT_VI = """Bạn cần tạo thêm {additional_count} câu hỏi trắc nghiệm BỔ SUNG.

NỘI DUNG TÀI LIỆU (CONTEXT):
{context}

CHỦ ĐỀ: {topic}
ĐỘ KHÓ: {difficulty}

CÁC CÂU HỎI ĐÃ CÓ (KHÔNG ĐƯỢC LẶP LẠI Ý):
{existing_questions}

QUY TẮC:
1. Tạo CHÍNH XÁC {additional_count} câu hỏi MỚI, KHÁC với các câu đã có
2. Mỗi câu có đúng 4 đáp án: A, B, C, D
3. CHỈ dùng thông tin trong context, KHÔNG bịa
4. Khai thác các khía cạnh/chi tiết CHƯA được hỏi
5. Giải thích ngắn gọn (1 câu)

ĐỊNH DẠNG OUTPUT (JSON):
{{
  "quiz": [
    {{
      "question": "Câu hỏi?",
      "options": ["Đáp án A", "Đáp án B", "Đáp án C", "Đáp án D"],
      "correct_answer": "A",
      "explanation": "Giải thích ngắn"
    }}
  ],
  "message": ""
}}

CHÚ Ý: Chỉ trả về JSON, không thêm text khác."""


QUIZ_SUPPLEMENT_PROMPT_EN = """You need to create {additional_count} ADDITIONAL multiple-choice questions.

DOCUMENT CONTENT:
{context}

TOPIC: {topic}
DIFFICULTY: {difficulty}

EXISTING QUESTIONS (DO NOT REPEAT):
{existing_questions}

RULES:
1. Create EXACTLY {additional_count} NEW questions, DIFFERENT from existing ones
2. Each question has exactly 4 options: A, B, C, D
3. Based ONLY on the provided content
4. Explore aspects/details NOT yet covered
5. Keep explanations brief (1 sentence)

OUTPUT FORMAT (JSON only):
{{
  "quiz": [
    {{
      "question": "Question?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer": "A",
      "explanation": "Brief explanation"
    }}
  ],
  "message": ""
}}

Return ONLY valid JSON, no additional text."""


# ===== Quiz Quality v2 Templates =====

QUIZ_GENERATION_PROMPT_VI_V2_BASE = """You are an expert teacher creating high-quality multiple-choice quiz questions.

QUIZ OUTPUT LANGUAGE: Vietnamese

SOURCE MATERIAL:
{context}

TOPIC / LEARNING SCOPE:
{topic}

DIFFICULTY:
{difficulty}

COVERAGE PLAN:
{blueprint_section}

GROUNDING CONTRACT:
1. Every correct answer must be directly supported by the source material.
2. You may use light background knowledge only to rephrase, connect nearby ideas, build simple in-scope scenarios, and write plausible distractors.
3. Never require outside facts to answer correctly.
4. Do not introduce advanced, tangential, or brand-new concepts outside the learning scope.

QUESTION COVERAGE:
- Mix question forms: definition, close comparison, cause-effect, condition/characteristic, process/order, light application, and negative form.
- Spread coverage across different supported ideas instead of paraphrasing the same detail repeatedly.
- Follow the coverage plan if provided, but treat it only as coverage guidance and NEVER copy it as draft quiz text.

DISTRACTOR RULES:
- Every wrong option must stay in the same domain and level of specificity as the correct option.
- Prefer traps such as: near miss, reversed condition, reversed cause-effect, scope confusion, true-but-not-answer, close concept confusion, and step-order confusion.
- Avoid absurd options, mismatched categories, noticeably shorter/longer options, giveaway wording, or obvious answer-position patterns.

QUALITY RULES:
- Each question must remain answerable from the source material alone.
- Keep the quiz fully in Vietnamese.
- __EXPLANATION_RULE__
- Do not mention option letters or option positions in the explanation.
- If the source is truly insufficient, return the maximum number of unique grounded questions without filler.

OUTPUT FORMAT (JSON only):
{{
  "quiz": [
    {{
      "question": "Noi dung cau hoi?",
      "options": ["Lua chon A", "Lua chon B", "Lua chon C", "Lua chon D"],
      "correct_answer": "A",
      "explanation": "Giai thich ngan gon"
    }}
  ],
  "message": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_GENERATION_PROMPT_EN_V2_BASE = """You are an expert teacher creating high-quality multiple-choice quiz questions.

QUIZ OUTPUT LANGUAGE: English

SOURCE MATERIAL:
{context}

TOPIC / LEARNING SCOPE:
{topic}

DIFFICULTY:
{difficulty}

COVERAGE PLAN:
{blueprint_section}

GROUNDING CONTRACT:
1. Every correct answer must be directly supported by the source material.
2. You may use light background knowledge only to rephrase, connect nearby ideas, build simple in-scope scenarios, and write plausible distractors.
3. Never require outside facts to answer correctly.
4. Do not introduce advanced, tangential, or brand-new concepts outside the learning scope.

QUESTION COVERAGE:
- Mix question forms: definition, close comparison, cause-effect, condition/characteristic, process/order, light application, and negative form.
- Spread coverage across different supported ideas instead of paraphrasing the same detail repeatedly.
- Follow the coverage plan if provided, but treat it only as coverage guidance and NEVER copy it as draft quiz text.

DISTRACTOR RULES:
- Every wrong option must stay in the same domain and level of specificity as the correct option.
- Prefer traps such as: near miss, reversed condition, reversed cause-effect, scope confusion, true-but-not-answer, close concept confusion, and step-order confusion.
- Avoid absurd options, mismatched categories, noticeably shorter/longer options, giveaway wording, or obvious answer-position patterns.

QUALITY RULES:
- Each question must remain answerable from the source material alone.
- Keep the quiz fully in English.
- __EXPLANATION_RULE__
- Do not mention option letters or option positions in the explanation.
- If the source is truly insufficient, return the maximum number of unique grounded questions without filler.

OUTPUT FORMAT (JSON only):
{{
  "quiz": [
    {{
      "question": "Question text?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer": "A",
      "explanation": "Brief explanation"
    }}
  ],
  "message": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_SUPPLEMENT_PROMPT_VI_V2 = """You need to create {additional_count} ADDITIONAL multiple-choice questions.

QUIZ OUTPUT LANGUAGE: Vietnamese

SOURCE MATERIAL:
{context}

TOPIC:
{topic}

DIFFICULTY:
{difficulty}

EXISTING QUESTIONS (DO NOT REPEAT OR PARAPHRASE):
{existing_questions}

GROUNDING CONTRACT:
1. Every correct answer must be directly supported by the source material.
2. You may use light background knowledge only to improve phrasing, connect nearby ideas, create simple in-scope scenarios, and write plausible distractors.
3. Never require outside facts to answer correctly.
4. Do not drift into advanced or tangential concepts outside the learning scope.

TARGETS:
- Explore angles not covered yet.
- Vary question forms and distractor traps.
- Keep wrong options plausible and same-domain.
- Keep explanations brief and grounded.
- Do not mention option letters in explanations.
- If the existing accepted questions are mostly recall/definition questions, generate at least one additional application or scenario-based question when the source material supports it.
- Application questions should ask learners to use a concept in a realistic situation, not just recall a definition.

LOW-VALUE QUESTION RESTRICTIONS:
- Avoid questions that only test administrative, biographical, or trivial metadata details.
- Do NOT generate questions whose primary purpose is recalling: instructor names, student names, phone numbers, email addresses, office locations, class schedules, course codes, IDs, document titles, file names, or trivial course metadata.
- Prefer questions that assess conceptual understanding, reasoning, application, comparison, cause-effect relationships, process understanding, or meaningful learning outcomes.
- Personal names should only appear when they are academically important to the learning content itself.
- Questions should prioritize educational and conceptual value over memorization of administrative details.

BAD QUESTION EXAMPLES (do NOT generate):
- "Giảng viên của khóa học Tương tác người máy là ai?"
- "Mã học phần của môn học là gì?"
GOOD QUESTION EXAMPLES (preferred style):
- "Gulf of execution mô tả khoảng cách nào trong tương tác người-máy?"
- "Khi người dùng hình thành ý định sai do mô hình tinh thần lệch, loại lỗi này được gọi là gì?"

MCQ STRUCTURAL CONSTRAINTS (HARD BAN — strictly enforced by post-validator):
1. EXACTLY ONE option is fully correct. The other 3 must each be independently wrong.
2. BANNED option phrases (DO NOT generate any option that matches or is semantically equivalent to these):
   - "all of the above", "none of the above", "all of these", "none of these"
   - "both A and B", "A and B only", "A and C", "B and C", "A, B and C", "all three answers"
   - "tất cả các đáp án trên", "tất cả đáp án trên", "tất cả đều đúng", "các ý trên đều đúng"
   - "cả 3 đáp án trên", "cả ba đáp án trên", "cả hai đáp án trên"
   - "không có đáp án nào đúng", "không đáp án nào đúng", "không có ý nào đúng"
   - "A và B", "A và C", "B và C", "A, B và C", "cả A và B", "cả A và C"
   - any option referencing other option letters/numbers, or aggregating them.
3. NO COMBINED / CUMULATIVE ANSWERS: an option must not be a superset or merger of other options' meanings.
4. INDEPENDENCE: the 4 options must be mutually exclusive; no two can be simultaneously true.
5. PARALLEL FORM: same grammatical type, roughly the same length. Correct option must not be noticeably longer than the longest distractor.
6. NO LEXICAL GIVEAWAY: correct option must not uniquely echo distinctive stem keywords or carry unique hedges ("always / never / chỉ / luôn luôn").

DISTRACTOR QUALITY RESTRICTIONS:
- Avoid answer choices that make the correct answer obvious by simple completeness.
- Do NOT create distractors that are merely extreme negations or artificial opposites of the correct answer.
- Avoid option sets where the choices follow a simplistic pattern such as:
  - only X
  - only Y
  - neither X nor Y
  - both X and Y
- Wrong options must be plausible misconceptions, not mechanically incomplete versions of the correct answer.
- All options should have a similar level of specificity, length, and conceptual depth.
- The correct answer should require understanding the concept, not just choosing the most complete or least extreme option.
- For questions about model components, processes, or frameworks, distractors should use plausible but incorrect components, relationships, or interpretations from the same domain.

BAD QUESTION (do NOT generate this style):
"Mô hình tương tác Abowd & Beale mô tả những thành phần nào trong tương tác người máy?"
A. Chỉ mô tả phía hệ thống
B. Không mô tả cả hai phía
C. Chỉ mô tả phía người dùng
D. Mô tả cả phía người dùng và phía hệ thống
Reason: The correct answer is obvious because it is the most complete option, while the distractors are simple incomplete opposites.

GOOD QUESTION (preferred style):
"Mô hình tương tác Abowd & Beale giúp phân tích tương tác người máy theo hướng nào?"
A. Phân tích tương tác thông qua các bước chuyển đổi giữa mục tiêu, thao tác, trạng thái hệ thống và phản hồi
B. Đánh giá giao diện chủ yếu dựa trên màu sắc, bố cục và mức độ thẩm mỹ trực quan
C. Mô tả hiệu năng hệ thống bằng các chỉ số phần cứng như bộ nhớ, CPU và tốc độ xử lý
D. Xác định vai trò của người dùng bằng cách phân loại họ theo trình độ kỹ thuật

BAD QUESTION (do NOT generate this style):
"Thiết kế giao diện tốt mang lại lợi ích gì?"
A. Không mang lại lợi ích nào
B. Chỉ giúp hệ thống đẹp hơn
C. Chỉ giúp người dùng thao tác nhanh hơn
D. Giúp cải thiện trải nghiệm, hiệu quả sử dụng và khả năng tiếp cận

GOOD QUESTION (preferred style):
"Trong HCI, vì sao thiết kế giao diện tốt có thể cải thiện hiệu quả sử dụng hệ thống?"
A. Vì nó giúp người dùng hiểu thao tác cần thực hiện, giảm lỗi và hoàn thành nhiệm vụ thuận lợi hơn
B. Vì nó thay thế hoàn toàn nhu cầu kiểm thử hệ thống với người dùng thật
C. Vì nó làm cho hệ thống có tốc độ xử lý cao hơn dù không thay đổi phần mềm bên trong
D. Vì nó đảm bảo mọi người dùng sẽ có cùng hành vi và cùng mức độ thành thạo

OUTPUT FORMAT (JSON only):
{{
  "quiz": [
    {{
      "question": "Noi dung cau hoi?",
      "options": ["Lua chon A", "Lua chon B", "Lua chon C", "Lua chon D"],
      "correct_answer": "A",
      "explanation": "Giai thich ngan gon"
    }}
  ],
  "message": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_SUPPLEMENT_PROMPT_EN_V2 = """You need to create {additional_count} ADDITIONAL multiple-choice questions.

QUIZ OUTPUT LANGUAGE: English

SOURCE MATERIAL:
{context}

TOPIC:
{topic}

DIFFICULTY:
{difficulty}

EXISTING QUESTIONS (DO NOT REPEAT OR PARAPHRASE):
{existing_questions}

GROUNDING CONTRACT:
1. Every correct answer must be directly supported by the source material.
2. You may use light background knowledge only to improve phrasing, connect nearby ideas, create simple in-scope scenarios, and write plausible distractors.
3. Never require outside facts to answer correctly.
4. Do not drift into advanced or tangential concepts outside the learning scope.

TARGETS:
- Explore angles not covered yet.
- Vary question forms and distractor traps.
- Keep wrong options plausible and same-domain.
- Keep explanations brief and grounded.
- Do not mention option letters in explanations.
- If the existing accepted questions are mostly recall/definition questions, generate at least one additional application or scenario-based question when the source material supports it.
- Application questions should ask learners to use a concept in a realistic situation, not just recall a definition.

LOW-VALUE QUESTION RESTRICTIONS:
- Avoid questions that only test administrative, biographical, or trivial metadata details.
- Do NOT generate questions whose primary purpose is recalling: instructor names, student names, phone numbers, email addresses, office locations, class schedules, course codes, IDs, document titles, file names, or trivial course metadata.
- Prefer questions that assess conceptual understanding, reasoning, application, comparison, cause-effect relationships, process understanding, or meaningful learning outcomes.
- Personal names should only appear when they are academically important to the learning content itself.
- Questions should prioritize educational and conceptual value over memorization of administrative details.

BAD QUESTION EXAMPLES (do NOT generate):
- "Who is the instructor of the Human-Computer Interaction course?"
- "What is the course code of this subject?"
GOOD QUESTION EXAMPLES (preferred style):
- "Which gap does the gulf of execution describe in human-computer interaction?"
- "When a user forms an incorrect intention because of a flawed mental model, what type of interaction error is this?"

MCQ STRUCTURAL CONSTRAINTS (HARD BAN — strictly enforced by post-validator):
1. EXACTLY ONE option is fully correct. The other 3 must each be independently wrong.
2. BANNED option phrases (DO NOT generate any option that matches or is semantically equivalent to these, in any language):
   - "all of the above", "none of the above", "all of these", "none of these"
   - "both A and B", "A and B only", "A and C", "B and C", "A, B and C", "all three answers"
   - "tất cả các đáp án trên", "tất cả đáp án trên", "tất cả đều đúng", "các ý trên đều đúng"
   - "cả 3 đáp án trên", "cả ba đáp án trên", "cả hai đáp án trên"
   - "không có đáp án nào đúng", "không đáp án nào đúng", "không có ý nào đúng"
   - "A và B", "A và C", "B và C", "A, B và C", "cả A và B", "cả A và C"
   - any option referencing other option letters/numbers, or aggregating them.
3. NO COMBINED / CUMULATIVE ANSWERS: an option must not be a superset or merger of other options' meanings.
4. INDEPENDENCE: the 4 options must be mutually exclusive; no two can be simultaneously true.
5. PARALLEL FORM: same grammatical type, roughly the same length. Correct option must not be noticeably longer than the longest distractor.
6. NO LEXICAL GIVEAWAY: correct option must not uniquely echo distinctive stem keywords or carry unique hedges ("always / never").

DISTRACTOR QUALITY RESTRICTIONS:
- Avoid answer choices that make the correct answer obvious by simple completeness.
- Do NOT create distractors that are merely extreme negations or artificial opposites of the correct answer.
- Avoid option sets where the choices follow a simplistic pattern such as:
  - only X
  - only Y
  - neither X nor Y
  - both X and Y
- Wrong options must be plausible misconceptions, not mechanically incomplete versions of the correct answer.
- All options should have a similar level of specificity, length, and conceptual depth.
- The correct answer should require understanding the concept, not just choosing the most complete or least extreme option.
- For questions about model components, processes, or frameworks, distractors should use plausible but incorrect components, relationships, or interpretations from the same domain.

BAD QUESTION (do NOT generate this style):
"Which components does the Abowd & Beale interaction model describe in human-computer interaction?"
A. Only the system side
B. Neither side is described
C. Only the user side
D. Both the user side and the system side
Reason: The correct answer is obvious because it is the most complete option, while the distractors are simple incomplete opposites.

GOOD QUESTION (preferred style):
"In what way does the Abowd & Beale interaction model help analyze human-computer interaction?"
A. It analyzes interaction through transitions between goals, actions, system state, and feedback
B. It evaluates the interface mainly based on color, layout, and visual aesthetics
C. It describes system performance using hardware metrics such as memory, CPU, and processing speed
D. It defines user roles by classifying them according to technical proficiency

BAD QUESTION (do NOT generate this style):
"What are the benefits of good interface design?"
A. It provides no benefits
B. It only makes the system look nicer
C. It only helps users operate faster
D. It improves user experience, efficiency, and accessibility

GOOD QUESTION (preferred style):
"In HCI, why can good interface design improve the effective use of a system?"
A. Because it helps users understand which actions to perform, reducing errors and easing task completion
B. Because it fully replaces the need for testing the system with real users
C. Because it makes the system process faster without changing the underlying software
D. Because it guarantees every user will exhibit the same behavior and proficiency level

OUTPUT FORMAT (JSON only):
{{
  "quiz": [
    {{
      "question": "Question text?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer": "A",
      "explanation": "Brief explanation"
    }}
  ],
  "message": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_BLUEPRINT_PROMPT_VI = """You are planning quiz coverage, not writing quiz questions.

QUIZ OUTPUT LANGUAGE: Vietnamese

SOURCE MATERIAL:
{context}

TOPIC:
{topic}

DIFFICULTY:
{difficulty}

Create a lightweight coverage plan for EXACTLY {num_questions} questions.

RULES:
1. The plan must stay within the learning scope supported by the source material.
2. The future correct answers must remain directly supportable by the source material.
3. Background knowledge may only help with phrasing ideas or plausible distractor strategy.
4. Do NOT write full questions, options, answers, or explanations.
5. Keep the plan compact and coverage-oriented.

OUTPUT FORMAT (JSON only):
{{
  "coverage_plan": [
    {{
      "coverage_item": "supported concept or subtopic",
      "evidence_refs": ["Document 1", "Document 3"],
      "question_form": "definition | comparison | cause_effect | condition | process | light_application | negative_form",
      "trap_type": "near_miss | reversed_condition | reversed_cause_effect | scope_confusion | true_but_not_answer | close_concept_confusion | step_order_confusion",
      "count": 2
    }}
  ],
  "notes": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_BLUEPRINT_PROMPT_EN = """You are planning quiz coverage, not writing quiz questions.

QUIZ OUTPUT LANGUAGE: English

SOURCE MATERIAL:
{context}

TOPIC:
{topic}

DIFFICULTY:
{difficulty}

Create a lightweight coverage plan for EXACTLY {num_questions} questions.

RULES:
1. The plan must stay within the learning scope supported by the source material.
2. The future correct answers must remain directly supportable by the source material.
3. Background knowledge may only help with phrasing ideas or plausible distractor strategy.
4. Do NOT write full questions, options, answers, or explanations.
5. Keep the plan compact and coverage-oriented.

OUTPUT FORMAT (JSON only):
{{
  "coverage_plan": [
    {{
      "coverage_item": "supported concept or subtopic",
      "evidence_refs": ["Document 1", "Document 3"],
      "question_form": "definition | comparison | cause_effect | condition | process | light_application | negative_form",
      "trap_type": "near_miss | reversed_condition | reversed_cause_effect | scope_confusion | true_but_not_answer | close_concept_confusion | step_order_confusion",
      "count": 2
    }}
  ],
  "notes": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUESTION_FORMS = [
    "definition",
    "comparison",
    "cause_effect",
    "condition",
    "process",
    "light_application",
    "negative_form",
]

# Hard-mode-only question forms requiring deeper reasoning
HARD_QUESTION_FORMS = [
    "multi_step_reasoning",
    "calculation",
    "scenario_application",
]

ALL_QUESTION_FORMS = QUESTION_FORMS + HARD_QUESTION_FORMS

TRAP_TYPES = [
    "near_miss",
    "reversed_condition",
    "reversed_cause_effect",
    "scope_confusion",
    "true_but_not_answer",
    "close_concept_confusion",
    "step_order_confusion",
]

# Hard-mode-only trap types requiring analytical errors
HARD_TRAP_TYPES = [
    "plausible_miscalculation",
    "incomplete_reasoning",
    "overgeneralization",
]

ALL_TRAP_TYPES = TRAP_TYPES + HARD_TRAP_TYPES

SUPPORTED_LEVELS = [
    "direct_source",
    "close_inference",
    "adjacent_in_scope",
]

# Hard-mode-only support level: answer synthesises info from 2+ source chunks
HARD_SUPPORTED_LEVELS = [
    "cross_chunk_synthesis",
]

ALL_SUPPORTED_LEVELS = SUPPORTED_LEVELS + HARD_SUPPORTED_LEVELS

# ---------------------------------------------------------------------------
# Difficulty policies – control question form mix, support levels, grounding,
# and prompt instructions per difficulty level.
# ---------------------------------------------------------------------------
DIFFICULTY_POLICIES: Dict[str, Dict[str, Any]] = {
    "easy": {
        "allowed_support_levels": ["direct_source"],
        "preferred_question_forms": ["definition", "process", "negative_form", "condition"],
        "allowed_question_forms": ["definition", "comparison", "cause_effect", "condition", "process", "negative_form"],
        "allowed_trap_types": TRAP_TYPES,
        "grounding": "strict",
        "blueprint_instruction": (
            "All slots must use support_level=direct_source only. "
            "Prefer simple question forms: definition, process, negative_form, condition. "
            "Coverage items should test recall of directly stated facts."
        ),
        "generation_instruction": (
            "DIFFICULTY POLICY (easy):\n"
            "- Questions must test direct recall of facts explicitly stated in the source.\n"
            "- Do NOT require inference, comparison across sections, or multi-step reasoning.\n"
            "- Distractors should be clearly wrong but plausible within the domain.\n"
            "- Each question should be answerable by reading a single relevant paragraph."
        ),
    },
    "medium": {
        "allowed_support_levels": ["direct_source", "close_inference"],
        "preferred_question_forms": QUESTION_FORMS,
        "allowed_question_forms": QUESTION_FORMS,
        "allowed_trap_types": TRAP_TYPES,
        "grounding": "standard",
        "blueprint_instruction": (
            "Use a balanced mix of support_level=direct_source and close_inference. "
            "Diversify question forms across definition, comparison, cause_effect, condition, "
            "process, light_application, and negative_form."
        ),
        "generation_instruction": (
            "DIFFICULTY POLICY (medium):\n"
            "- Questions should test understanding and application of concepts from the source.\n"
            "- Mix direct recall with light inference from nearby supported details.\n"
            "- Distractors should be plausible alternatives that require careful reading to eliminate.\n"
            "- Some questions may require connecting two closely related ideas from the source."
        ),
    },
    "hard": {
        "allowed_support_levels": ["direct_source", "close_inference", "cross_chunk_synthesis"],
        "preferred_question_forms": [
            "cause_effect", "comparison", "light_application",
            "multi_step_reasoning", "calculation", "scenario_application",
        ],
        "allowed_question_forms": ALL_QUESTION_FORMS,
        "allowed_trap_types": ALL_TRAP_TYPES,
        "grounding": "relaxed_with_guardrails",
        "blueprint_instruction": (
            "Allocate at least 30%% of slots to support_level=cross_chunk_synthesis "
            "(answer requires combining info from 2+ parts of the source). "
            "Prefer advanced question forms: multi_step_reasoning, calculation, "
            "scenario_application, cause_effect, comparison. "
            "Coverage items should target deeper analysis, not surface-level recall."
        ),
        "generation_instruction": (
            "DIFFICULTY POLICY (hard):\n"
            "- Questions MUST require genuine analytical thinking, not just recall.\n"
            "- For cross_chunk_synthesis slots: combine information from multiple parts of the source "
            "to form a question that cannot be answered from a single paragraph alone.\n"
            "- For multi_step_reasoning slots: require 2 or more logical steps to reach the answer.\n"
            "- For calculation slots: apply a formula, method, or quantitative relationship from the source to derive the answer.\n"
            "- For scenario_application slots: present a new but realistic scenario solvable using knowledge from the source.\n"
            "- Distractors MUST be plausible analytical errors (e.g., reversed causality, incomplete reasoning, "
            "overgeneralization, plausible miscalculation) — NOT simple factual alternatives.\n"
            "- Do NOT create trick questions or ambiguous questions. The correct answer must still be "
            "unambiguously derivable from the source material.\n"
            "- Every correct answer must remain traceable to the source — no outside knowledge required."
        ),
    },
}

LARGE_REQUEST_QUESTION_THRESHOLD = 36
MAX_LLM_CALLS_PER_LARGE_QUIZ_NO_BLUEPRINT = 8
MAX_LLM_CALLS_PER_LARGE_QUIZ_WITH_BLUEPRINT = 10
MAX_EST_COMPLETION_TOKENS_PER_LARGE_QUIZ = 20_000
PARTIAL_SUCCESS_RATIO = 0.95

# Chunked blueprint: max slots per single blueprint LLM call
BLUEPRINT_CHUNK_SIZE = 20

QUIZ_GENERATION_PROMPT_VNEXT_VI = """You are an expert university-level Human-Computer Interaction (HCI) teacher creating professional multiple-choice quiz questions for students.

QUIZ OUTPUT LANGUAGE: Vietnamese
GENERATION MODE: {generation_mode}
TOTAL TARGET: {total_target}
BATCH TARGET: {batch_target}

TOPIC / LEARNING SCOPE:
{topic}

DIFFICULTY:
{difficulty}

{difficulty_policy}

ASSIGNED SLOTS:
{slot_section}

ALREADY GENERATED QUESTIONS (DO NOT REPEAT OR PARAPHRASE):
{existing_questions}

SOURCE MATERIAL:
{context}

PEDAGOGICAL GOAL:
Generate multiple-choice questions for Human-Computer Interaction that cover multiple cognitive levels, not only memorization and not only difficult application.

The quiz should include a balanced mix of:
- Recognition / Understanding: recall key concepts, identify definitions, distinguish related terms.
- Application: apply a concept, model, principle, or interaction style to a realistic HCI situation.
- Advanced Application / Analysis: diagnose a design problem, compare alternatives, reason across multiple concepts, or select the best design decision under constraints.

DEFAULT COGNITIVE LEVEL DISTRIBUTION:
Unless ASSIGNED SLOTS specify otherwise, use approximately:
- 30% recognition_understanding
- 50% application
- 20% advanced_application_analysis

For a 10-question quiz, prefer:
- 3 recognition_understanding questions
- 5 application questions
- 2 advanced_application_analysis questions

COGNITIVE LEVEL DEFINITIONS:
1. recognition_understanding:
   - Ask students to recognize, define, classify, or distinguish important concepts from the source.
   - Suitable forms: definition, concept identification, term matching, simple comparison.
   - Avoid copying exact sentences from the source.
   - The question should still require understanding, not merely spotting a word.

2. application:
   - Present a simple but realistic HCI scenario.
   - Require students to apply one concept from the source to choose the best answer.
   - Suitable forms: scenario_application, simple diagnosis, choosing a suitable interaction style, identifying a gulf/error/interface element.

3. advanced_application_analysis:
   - Present a richer scenario with constraints, trade-offs, or multiple interacting concepts.
   - Require at least two reasoning steps.
   - Suitable forms: multi_step_reasoning, comparison, diagnosis, design_improvement.
   - The answer should not be directly copied from the source, but must be grounded in it.

GROUNDING POLICY:
1. Every correct answer must stay anchored to the source material.
2. support_level=direct_source means the answer is directly stated in the source.
3. support_level=close_inference means the answer is a short inference from nearby supported details.
4. support_level=cross_chunk_synthesis means the answer requires combining information from 2 or more distinct parts of the source material.
5. support_level=adjacent_in_scope is allowed only for missing-slot refill and must remain very close to supported concepts from the source.
6. Never require outside facts such as dates, authors, formulas, benchmarks, or advanced concepts not supported by the source.
7. Background knowledge may only help phrasing, simple in-scope scenarios, and plausible distractors.

SOURCE ROLES:
- Each chunk in SOURCE MATERIAL may be tagged [lecture] or [domain]. Untagged chunks are treated as [lecture].
- [lecture] chunks define the in-scope topics that questions MUST be about.
- [domain] chunks are course-level shared knowledge meant to add depth, examples, or precise terminology to a concept that is already covered by a [lecture] chunk.
- Do NOT generate any question whose answer is supported ONLY by [domain] chunks.
- Every question's anchoring evidence must include at least one [lecture] chunk.
- When a fact appears in both [lecture] and [domain] chunks, prefer the wording, scope, and emphasis of the [lecture] chunk.

QUESTION RULES:
- Produce exactly one question per slot and preserve every slot_id.
- Follow each slot's topic_group, coverage_item, support_level, question_form, trap_type, and cognitive_level if provided.
- Keep questions diverse, in-scope, and non-redundant.
- Provide exactly 4 plausible options in the same domain and level of specificity.
- The correct option must be clearly best according to the source material.
- Distractors must be plausible HCI misunderstandings, not obviously wrong or unrelated choices.
- Avoid negative questions such as "Which is NOT correct?" unless required by the trap_type.
- Do not output explanations or feedback text.

LOW-VALUE QUESTION RESTRICTIONS:
- Avoid questions that only test administrative, biographical, or trivial metadata details.
- Do NOT generate questions whose primary purpose is recalling: instructor names, student names, phone numbers, email addresses, office locations, class schedules, course codes, IDs, document titles, file names, or trivial course metadata.
- Prefer questions that assess conceptual understanding, reasoning, application, comparison, cause-effect relationships, process understanding, or meaningful learning outcomes.
- Personal names should only appear when they are academically important to the learning content itself.
- Questions should prioritize educational and conceptual value over memorization of administrative details.

APPLICATION QUESTION GUIDELINES:
- When a slot has cognitive_level=concept_application, scenario_application, or advanced_application_analysis, write a question that requires applying the source concept to a realistic situation.
- The scenario should be concise but meaningful.
- The correct answer should require reasoning from the source concept, not merely repeating a phrase from the source.
- Distractors should represent plausible but flawed decisions, misconceptions, or trade-offs.
- Avoid making the correct option obvious by being the only complete or positive answer.
- Keep the scenario realistic for the learning domain, such as user behavior, interface design, system use, classroom learning, product design, or decision-making contexts.
- Do not introduce outside facts that are not needed to answer the question.

BAD QUESTION EXAMPLES (do NOT generate):
- "Giảng viên của khóa học Tương tác người máy là ai?"
- "Mã học phần của môn học là gì?"
GOOD QUESTION EXAMPLES (preferred style):
- "Gulf of execution mô tả khoảng cách nào trong tương tác người-máy?"
- "Khi người dùng hình thành ý định sai do mô hình tinh thần lệch, loại lỗi này được gọi là gì?"

MCQ STRUCTURAL CONSTRAINTS (HARD BAN — strictly enforced by post-validator):
1. EXACTLY ONE option is fully correct. The other 3 must each contain at least one factual or reasoning error that makes them clearly wrong on their own.
2. BANNED option phrases (DO NOT generate any option that matches or is semantically equivalent to these, in any language):
   - "all of the above", "none of the above", "all of these", "none of these"
   - "both A and B", "A and B only", "A and C", "B and C", "A, B and C", "all three answers"
   - "tất cả các đáp án trên", "tất cả đáp án trên", "tất cả đều đúng", "các ý trên đều đúng"
   - "cả 3 đáp án trên", "cả ba đáp án trên", "cả hai đáp án trên"
   - "không có đáp án nào đúng", "không đáp án nào đúng", "không có ý nào đúng"
   - "A và B", "A và C", "B và C", "A, B và C", "cả A và B", "cả A và C"
   - any option that references other option letters / numbers, or aggregates them.
3. NO COMBINED / CUMULATIVE ANSWERS: an option must not be a superset, sum, or merger of the meaning of other options. Each option must be independently true-or-false.
4. INDEPENDENCE & EXCLUSIVITY: the 4 options must be mutually exclusive — no two options can be simultaneously true given the stem.
5. PARALLEL FORM: all 4 options must be the same grammatical type (all noun phrases, OR all full sentences, OR all numeric values) and roughly the same length. The correct option must NOT be noticeably longer than the longest distractor.
6. NO LEXICAL GIVEAWAY: the correct option must not be the only one that echoes distinctive keywords from the stem, and must not be the only one carrying hedges like "always / never / chỉ / luôn luôn" unless all 4 do.
7. SINGLE BEST ANSWER TEST: if a careful student can defend 2+ options as correct from the source, REWRITE the stem or the options before returning.

DISTRACTOR QUALITY RESTRICTIONS:
- Avoid answer choices that make the correct answer obvious by simple completeness.
- Do NOT create distractors that are merely extreme negations or artificial opposites of the correct answer.
- Avoid option sets where the choices follow a simplistic pattern such as:
  - only X
  - only Y
  - neither X nor Y
  - both X and Y
- Wrong options must be plausible misconceptions, not mechanically incomplete versions of the correct answer.
- All options should have a similar level of specificity, length, and conceptual depth.
- The correct answer should require understanding the concept, not just choosing the most complete or least extreme option.
- For questions about model components, processes, or frameworks, distractors should use plausible but incorrect components, relationships, or interpretations from the same domain.

BAD QUESTION (do NOT generate this style):
"Mô hình tương tác Abowd & Beale mô tả những thành phần nào trong tương tác người máy?"
A. Chỉ mô tả phía hệ thống
B. Không mô tả cả hai phía
C. Chỉ mô tả phía người dùng
D. Mô tả cả phía người dùng và phía hệ thống
Reason: The correct answer is obvious because it is the most complete option, while the distractors are simple incomplete opposites.

GOOD QUESTION (preferred style):
"Mô hình tương tác Abowd & Beale giúp phân tích tương tác người máy theo hướng nào?"
A. Phân tích tương tác thông qua các bước chuyển đổi giữa mục tiêu, thao tác, trạng thái hệ thống và phản hồi
B. Đánh giá giao diện chủ yếu dựa trên màu sắc, bố cục và mức độ thẩm mỹ trực quan
C. Mô tả hiệu năng hệ thống bằng các chỉ số phần cứng như bộ nhớ, CPU và tốc độ xử lý
D. Xác định vai trò của người dùng bằng cách phân loại họ theo trình độ kỹ thuật

BAD QUESTION (do NOT generate this style):
"Thiết kế giao diện tốt mang lại lợi ích gì?"
A. Không mang lại lợi ích nào
B. Chỉ giúp hệ thống đẹp hơn
C. Chỉ giúp người dùng thao tác nhanh hơn
D. Giúp cải thiện trải nghiệm, hiệu quả sử dụng và khả năng tiếp cận

GOOD QUESTION (preferred style):
"Trong HCI, vì sao thiết kế giao diện tốt có thể cải thiện hiệu quả sử dụng hệ thống?"
A. Vì nó giúp người dùng hiểu thao tác cần thực hiện, giảm lỗi và hoàn thành nhiệm vụ thuận lợi hơn
B. Vì nó thay thế hoàn toàn nhu cầu kiểm thử hệ thống với người dùng thật
C. Vì nó làm cho hệ thống có tốc độ xử lý cao hơn dù không thay đổi phần mềm bên trong
D. Vì nó đảm bảo mọi người dùng sẽ có cùng hành vi và cùng mức độ thành thạo

BAD QUESTION (recall-only, do NOT generate this style for application slots):
"Thiết kế giao diện tốt mang lại lợi ích gì?"
A. Không có lợi ích gì
B. Chỉ giúp giao diện đẹp hơn
C. Chỉ giúp hệ thống chạy nhanh hơn
D. Giúp cải thiện trải nghiệm người dùng và hiệu quả sử dụng

GOOD APPLICATION QUESTION (preferred style for application/scenario slots):
"Một nhóm phát triển ứng dụng đang phân vân giữa phát hành nhanh với giao diện đơn giản chưa kiểm thử và đầu tư thêm vào UI/UX trước khi ra mắt. Dựa trên lợi ích của thiết kế giao diện tốt, lập luận nào hỗ trợ tốt nhất việc đầu tư thêm vào UI/UX?"
A. UI/UX chỉ làm tăng thời gian phát triển và không ảnh hưởng đến người dùng.
B. Chỉ cần có nhiều chức năng thì người dùng sẽ tự thích nghi với giao diện.
C. Thiết kế UI tốt có thể tăng khả năng chấp nhận sản phẩm, giảm lỗi sử dụng và giảm chi phí sửa lỗi giao diện về sau.
D. Giao diện chỉ cần đẹp, không cần hỗ trợ hiệu quả thao tác.

QUESTION FORM GUIDANCE:
- recognition_understanding questions may ask about key terms such as domain, task, goal, intention, gulf of execution, gulf of evaluation, slip, mistake, ergonomics, WIMP elements, or interaction styles.
- application questions should use short scenarios such as printing a document, filling a form, using an ATM, using menus, command line, voice input, or WIMP elements.
- advanced_application_analysis questions should involve trade-offs, diagnosing the root cause of an interaction failure, or choosing a design improvement under constraints.

TRAP / DISTRACTOR POLICY:
Use distractors to test common HCI misconceptions, such as:
- confusing gulf of execution with gulf of evaluation,
- confusing slip with mistake,
- confusing recognition-based menu interaction with recall-based command interaction,
- assuming a visually attractive interface is always more usable,
- assuming natural language interfaces are always easy for machines to understand,
- confusing input-side issues with output-side issues in the interaction framework,
- choosing more features instead of reducing cognitive or physical burden.

QUALITY CHECK BEFORE OUTPUT:
Before returning JSON, silently verify:
1. The quiz follows the intended cognitive level distribution.
2. Each question is answerable from the source material.
3. Recognition questions are not too trivial.
4. Application questions require applying a concept to a situation.
5. Advanced questions require at least two reasoning steps or a meaningful trade-off.
6. The correct answer is uniquely best.
7. All distractors are plausible but clearly less suitable.
8. The output is valid JSON only.

OUTPUT FORMAT (JSON only):
{{
  "quiz": [
    {{
      "slot_id": "S01",
      "cognitive_level": "recognition_understanding",
      "question": "Nội dung câu hỏi?",
      "options": ["Lựa chọn A", "Lựa chọn B", "Lựa chọn C", "Lựa chọn D"],
      "correct_answer": "A"
    }}
  ],
  "message": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_GENERATION_PROMPT_VNEXT_EN = """You are an expert teacher creating professional multiple-choice quiz questions.

QUIZ OUTPUT LANGUAGE: English
GENERATION MODE: {generation_mode}
TOTAL TARGET: {total_target}
BATCH TARGET: {batch_target}

TOPIC / LEARNING SCOPE:
{topic}

DIFFICULTY:
{difficulty}

{difficulty_policy}

ASSIGNED SLOTS:
{slot_section}

ALREADY GENERATED QUESTIONS (DO NOT REPEAT OR PARAPHRASE):
{existing_questions}

SOURCE MATERIAL:
{context}

GROUNDING POLICY:
1. Every correct answer must stay anchored to the source material.
2. support_level=direct_source means the answer is directly stated in the source.
3. support_level=close_inference means the answer is a short inference from nearby supported details.
4. support_level=cross_chunk_synthesis means the answer requires combining information from 2 or more distinct parts of the source material.
5. support_level=adjacent_in_scope is allowed only for missing-slot refill and must remain very close to supported concepts from the source.
6. Never require outside facts such as dates, authors, formulas, benchmarks, or advanced concepts not supported by the source.
7. Background knowledge may only help phrasing, simple in-scope scenarios, and plausible distractors.

SOURCE ROLES:
- Each chunk in SOURCE MATERIAL may be tagged [lecture] or [domain]. Untagged chunks are treated as [lecture].
- [lecture] chunks define the in-scope topics that questions MUST be about.
- [domain] chunks are course-level shared knowledge meant to add depth, examples, or precise terminology to a concept that is already covered by a [lecture] chunk.
- Do NOT generate any question whose answer is supported ONLY by [domain] chunks. Every question's anchoring evidence must include at least one [lecture] chunk.
- When a fact appears in both [lecture] and [domain] chunks, prefer the wording, scope, and emphasis of the [lecture] chunk.

QUESTION RULES:
- Produce exactly one question per slot and preserve every slot_id.
- Follow each slot's topic_group, coverage_item, support_level, question_form, trap_type, and cognitive_level if provided.
- Keep questions diverse, in-scope, and non-redundant.
- Provide exactly 4 plausible options in the same domain and level of specificity.
- Do not output explanations or feedback text.
- question_form=multi_step_reasoning: require 2+ logical steps to reach the answer.
- question_form=calculation: apply a formula or quantitative relationship from the source.
- question_form=scenario_application: present a realistic new scenario solvable using source knowledge.

APPLICATION QUESTION GUIDELINES:
- When a slot has cognitive_level=concept_application, scenario_application, or advanced_application_analysis, write a question that requires applying the source concept to a realistic situation.
- The scenario should be concise but meaningful.
- The correct answer should require reasoning from the source concept, not merely repeating a phrase from the source.
- Distractors should represent plausible but flawed decisions, misconceptions, or trade-offs.
- Avoid making the correct option obvious by being the only complete or positive answer.
- Keep the scenario realistic for the learning domain, such as user behavior, interface design, system use, classroom learning, product design, or decision-making contexts.
- Do not introduce outside facts that are not needed to answer the question.

LOW-VALUE QUESTION RESTRICTIONS:
- Avoid questions that only test administrative, biographical, or trivial metadata details.
- Do NOT generate questions whose primary purpose is recalling: instructor names, student names, phone numbers, email addresses, office locations, class schedules, course codes, IDs, document titles, file names, or trivial course metadata.
- Prefer questions that assess conceptual understanding, reasoning, application, comparison, cause-effect relationships, process understanding, or meaningful learning outcomes.
- Personal names should only appear when they are academically important to the learning content itself.
- Questions should prioritize educational and conceptual value over memorization of administrative details.

BAD QUESTION EXAMPLES (do NOT generate):
- "Who is the instructor of the Human-Computer Interaction course?"
- "What is the course code of this subject?"
GOOD QUESTION EXAMPLES (preferred style):
- "Which gap does the gulf of execution describe in human-computer interaction?"
- "When a user forms an incorrect intention because of a flawed mental model, what type of interaction error is this?"

MCQ STRUCTURAL CONSTRAINTS (HARD BAN — strictly enforced by post-validator):
1. EXACTLY ONE option is fully correct. The other 3 must each contain at least one factual or reasoning error that makes them clearly wrong on their own.
2. BANNED option phrases (DO NOT generate any option that matches or is semantically equivalent to these, in any language):
   - "all of the above", "none of the above", "all of these", "none of these"
   - "both A and B", "A and B only", "A and C", "B and C", "A, B and C", "all three answers"
   - "tất cả các đáp án trên", "tất cả đáp án trên", "tất cả đều đúng", "các ý trên đều đúng"
   - "cả 3 đáp án trên", "cả ba đáp án trên", "cả hai đáp án trên"
   - "không có đáp án nào đúng", "không đáp án nào đúng", "không có ý nào đúng"
   - "A và B", "A và C", "B và C", "A, B và C", "cả A và B", "cả A và C"
   - any option that references other option letters / numbers, or aggregates them.
3. NO COMBINED / CUMULATIVE ANSWERS: an option must not be a superset, sum, or merger of the meaning of other options. Each option must be independently true-or-false.
4. INDEPENDENCE & EXCLUSIVITY: the 4 options must be mutually exclusive — no two options can be simultaneously true given the stem.
5. PARALLEL FORM: all 4 options must be the same grammatical type and roughly the same length. The correct option must NOT be noticeably longer than the longest distractor.
6. NO LEXICAL GIVEAWAY: the correct option must not uniquely echo distinctive stem keywords, and must not be the only one carrying hedges like "always / never" unless all 4 do.
7. SINGLE BEST ANSWER TEST: if 2+ options could be defended from the source, REWRITE the stem or the options before returning.

DISTRACTOR QUALITY RESTRICTIONS:
- Avoid answer choices that make the correct answer obvious by simple completeness.
- Do NOT create distractors that are merely extreme negations or artificial opposites of the correct answer.
- Avoid option sets where the choices follow a simplistic pattern such as:
  - only X
  - only Y
  - neither X nor Y
  - both X and Y
- Wrong options must be plausible misconceptions, not mechanically incomplete versions of the correct answer.
- All options should have a similar level of specificity, length, and conceptual depth.
- The correct answer should require understanding the concept, not just choosing the most complete or least extreme option.
- For questions about model components, processes, or frameworks, distractors should use plausible but incorrect components, relationships, or interpretations from the same domain.

BAD QUESTION (do NOT generate this style):
"Which components does the Abowd & Beale interaction model describe in human-computer interaction?"
A. Only the system side
B. Neither side is described
C. Only the user side
D. Both the user side and the system side
Reason: The correct answer is obvious because it is the most complete option, while the distractors are simple incomplete opposites.

GOOD QUESTION (preferred style):
"In what way does the Abowd & Beale interaction model help analyze human-computer interaction?"
A. It analyzes interaction through transitions between goals, actions, system state, and feedback
B. It evaluates the interface mainly based on color, layout, and visual aesthetics
C. It describes system performance using hardware metrics such as memory, CPU, and processing speed
D. It defines user roles by classifying them according to technical proficiency

BAD QUESTION (do NOT generate this style):
"What are the benefits of good interface design?"
A. It provides no benefits
B. It only makes the system look nicer
C. It only helps users operate faster
D. It improves user experience, efficiency, and accessibility

GOOD QUESTION (preferred style):
"In HCI, why can good interface design improve the effective use of a system?"
A. Because it helps users understand which actions to perform, reducing errors and easing task completion
B. Because it fully replaces the need for testing the system with real users
C. Because it makes the system process faster without changing the underlying software
D. Because it guarantees every user will exhibit the same behavior and proficiency level

BAD QUESTION (recall-only, do NOT generate this style for application slots):
"What are the benefits of good interface design?"
A. It has no benefits
B. It only makes the interface look nicer
C. It only makes the system run faster
D. It improves user experience and effectiveness

GOOD APPLICATION QUESTION (preferred style for application/scenario slots):
"A development team is debating whether to ship quickly with a simple, untested interface or invest more time in UI/UX before launch. Based on the benefits of good interface design, which argument best supports investing more in UI/UX?"
A. UI/UX only adds development time and does not affect users.
B. As long as the app has many features, users will adapt to any interface on their own.
C. Good UI design can increase product adoption, reduce usage errors, and lower the cost of fixing interface issues later.
D. The interface only needs to look nice; it does not need to support effective interaction.

OUTPUT FORMAT (JSON only):
{{
  "quiz": [
    {{
      "slot_id": "S01",
      "question": "Question text?",
      "options": ["Option A", "Option B", "Option C", "Option D"],
      "correct_answer": "A"
    }}
  ],
  "message": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_SLOT_BLUEPRINT_PROMPT_VI = """You are planning quiz coverage, not writing quiz questions.

QUIZ OUTPUT LANGUAGE: Vietnamese

SOURCE MATERIAL:
{context}

REQUESTED TOPICS:
{topic}

DIFFICULTY:
{difficulty}

{difficulty_policy}

Create an exact slot blueprint for {num_questions} quiz questions.

RULES:
1. Normalize overlapping requested topics into topic groups when appropriate.
2. Each slot must stay inside the supported learning scope.
3. support_level may be: direct_source, close_inference, or cross_chunk_synthesis (hard mode only).
4. question_form may be: definition, comparison, cause_effect, condition, process, light_application, negative_form, multi_step_reasoning, calculation, scenario_application.
5. trap_type may be: near_miss, reversed_condition, reversed_cause_effect, scope_confusion, true_but_not_answer, close_concept_confusion, step_order_confusion, plausible_miscalculation, incomplete_reasoning, overgeneralization.
6. cognitive_level may be: remember_understand, concept_application, scenario_application, advanced_application_analysis.
7. Do NOT write full questions, answer options, correct answers, or explanations.
8. Prefer broad coverage and professional diversity instead of paraphrasing the same idea.
9. LOW-VALUE COVERAGE RESTRICTIONS: Do NOT plan slots that target administrative or biographical metadata such as instructor names, student names, phone numbers, emails, office locations, class schedules, course codes, IDs, document titles, file names, or trivial course metadata. Prefer coverage items that target conceptual understanding, reasoning, application, comparison, cause-effect relationships, or process understanding.

APPLICATION / ANALYSIS SLOT REQUIREMENTS:
- For quizzes with 5 or more questions, allocate at least 1 slot to application or scenario-based reasoning when the source material supports it.
- For quizzes with 10 or more questions, allocate 2-3 slots to application, scenario_application, multi_step_reasoning, cause_effect, or advanced comparison when supported by the source.
- These slots should ask learners to apply concepts to realistic situations, user behaviors, interface problems, product decisions, learning contexts, or design trade-offs.
- Do not force application slots if the source material only contains isolated administrative facts or very shallow definitions.
- Application slots must still remain grounded in the lecture/source material.
- Set cognitive_level=concept_application, scenario_application, or advanced_application_analysis on application/analysis slots; use cognitive_level=remember_understand for recall/definition slots.

OUTPUT FORMAT (JSON only):
{{
  "topic_groups": [
    {{
      "group_id": "G1",
      "label": "Ten nhom chu de",
      "source_topics": ["topic A", "topic B"],
      "evidence_refs": ["Document 1", "Document 3"]
    }}
  ],
  "slots": [
    {{
      "slot_id": "S01",
      "topic_group": "G1",
      "coverage_item": "supported concept",
      "support_level": "direct_source",
      "question_form": "definition",
      "trap_type": "near_miss",
      "cognitive_level": "remember_understand"
    }}
  ],
  "notes": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


QUIZ_SLOT_BLUEPRINT_PROMPT_EN = """You are planning quiz coverage, not writing quiz questions.

QUIZ OUTPUT LANGUAGE: English

SOURCE MATERIAL:
{context}

REQUESTED TOPICS:
{topic}

DIFFICULTY:
{difficulty}

{difficulty_policy}

Create an exact slot blueprint for {num_questions} quiz questions.

RULES:
1. Normalize overlapping requested topics into topic groups when appropriate.
2. Each slot must stay inside the supported learning scope.
3. support_level may be: direct_source, close_inference, or cross_chunk_synthesis (hard mode only).
4. question_form may be: definition, comparison, cause_effect, condition, process, light_application, negative_form, multi_step_reasoning, calculation, scenario_application.
5. trap_type may be: near_miss, reversed_condition, reversed_cause_effect, scope_confusion, true_but_not_answer, close_concept_confusion, step_order_confusion, plausible_miscalculation, incomplete_reasoning, overgeneralization.
6. cognitive_level may be: remember_understand, concept_application, scenario_application, advanced_application_analysis.
7. Do NOT write full questions, answer options, correct answers, or explanations.
8. Prefer broad coverage and professional diversity instead of paraphrasing the same idea.
9. LOW-VALUE COVERAGE RESTRICTIONS: Do NOT plan slots that target administrative or biographical metadata such as instructor names, student names, phone numbers, emails, office locations, class schedules, course codes, IDs, document titles, file names, or trivial course metadata. Prefer coverage items that target conceptual understanding, reasoning, application, comparison, cause-effect relationships, or process understanding.

APPLICATION / ANALYSIS SLOT REQUIREMENTS:
- For quizzes with 5 or more questions, allocate at least 1 slot to application or scenario-based reasoning when the source material supports it.
- For quizzes with 10 or more questions, allocate 2-3 slots to application, scenario_application, multi_step_reasoning, cause_effect, or advanced comparison when supported by the source.
- These slots should ask learners to apply concepts to realistic situations, user behaviors, interface problems, product decisions, learning contexts, or design trade-offs.
- Do not force application slots if the source material only contains isolated administrative facts or very shallow definitions.
- Application slots must still remain grounded in the lecture/source material.
- Set cognitive_level=concept_application, scenario_application, or advanced_application_analysis on application/analysis slots; use cognitive_level=remember_understand for recall/definition slots.

OUTPUT FORMAT (JSON only):
{{
  "topic_groups": [
    {{
      "group_id": "G1",
      "label": "Topic group label",
      "source_topics": ["topic A", "topic B"],
      "evidence_refs": ["Document 1", "Document 3"]
    }}
  ],
  "slots": [
    {{
      "slot_id": "S01",
      "topic_group": "G1",
      "coverage_item": "supported concept",
      "support_level": "direct_source",
      "question_form": "definition",
      "trap_type": "near_miss",
      "cognitive_level": "remember_understand"
    }}
  ],
  "notes": ""
}}

Return ONLY valid JSON, no markdown, no extra text."""


# ===========================================================================
# MCQ Structural Validation (P0)
# ---------------------------------------------------------------------------
# Heuristic post-validator that rejects malformed multiple-choice questions
# such as "All of the above", combined-answer options, length-bias correct
# answers, and obvious meta-options. Rejected questions are returned to the
# pipeline as malformed so the slot is refilled via the supplement pass.
# ===========================================================================

# Hard-banned literal phrases (matched as whole-string equality after
# normalization). Covers VI + EN aggregator answers.
_BANNED_OPTION_LITERALS_NORMALIZED = {
    # English
    "all of the above",
    "all the above",
    "all of these",
    "none of the above",
    "none of these",
    "all answers are correct",
    "all of the answers are correct",
    "no correct answer",
    "no answer is correct",
    "all three answers",
    "all four answers",
    # Vietnamese
    "tat ca cac dap an tren",
    "tat ca dap an tren",
    "tat ca y tren",
    "tat ca cac y tren",
    "cac y tren deu dung",
    "cac dap an tren deu dung",
    "tat ca deu dung",
    "tat ca cac phuong an tren",
    "tat ca phuong an tren",
    "ca 3 dap an tren",
    "ca ba dap an tren",
    "ca hai dap an tren",
    "ca 2 dap an tren",
    "khong co dap an nao dung",
    "khong dap an nao dung",
    "khong co y nao dung",
    "khong y nao dung",
    "khong co phuong an nao dung",
}

# Regex patterns that catch combined / cumulative answers like
# "Both A and C", "A and B only", "1 and 3", "Cả A và B", "đáp án A và C".
# Each pattern is conservative: it requires an option-letter pair anchored
# to the option string (whole-string or with explicit option/answer marker).
_BANNED_OPTION_REGEXES = [
    # English combined
    re.compile(r"\bboth\s+[abcd1234]\s+and\s+[abcd1234]\b", re.IGNORECASE),
    re.compile(r"\b[abcd1234]\s+and\s+[abcd1234]\s+only\b", re.IGNORECASE),
    # Bare "A and C" / "B and C" as the entire option (anchored).
    re.compile(r"^\s*[abcd1234]\s+and\s+[abcd1234]\s*$", re.IGNORECASE),
    re.compile(r"\b[abcd1234]\s*,\s*[abcd1234]\s+and\s+[abcd1234]\b", re.IGNORECASE),
    re.compile(r"\b(options?|answers?|choices?)\s+[abcd1234]\s+and\s+[abcd1234]\b", re.IGNORECASE),
    # Vietnamese combined — require explicit "cả/đáp án/phương án" marker so
    # we don't falsely match prose like "phân tích A và C trong sơ đồ".
    re.compile(r"\b(cả|ca)\s+[abcd1234]\s+(và|va)\s+[abcd1234]\b", re.IGNORECASE),
    re.compile(r"\b(đáp\s*án|dap\s*an|phương\s*án|phuong\s*an|ý kiến|y kien)\s+[abcd1234]\s+(và|va)\s+[abcd1234]\b", re.IGNORECASE),
    # Bare "A và C" anchored to the entire option.
    re.compile(r"^\s*[abcd1234]\s+(và|va)\s+[abcd1234]\s*$", re.IGNORECASE),
]

# Multi-word phrases that strongly indicate an aggregator option even if not
# on the literal ban list. Single tokens like "tat ca" / "ca hai" / "deu dung"
# are deliberately NOT here — they appear in many legitimate options.
_SUSPICIOUS_META_PHRASES_NORMALIZED = (
    "all of the above",
    "none of the above",
    "tat ca cac y tren",
    "tat ca y tren",
    "tat ca dap an tren",
    "tat ca phuong an tren",
    "cac y tren deu dung",
    "cac dap an tren deu dung",
)

# Connector tokens that must appear in an option before the combined-superset
# heuristic is allowed to flag it. Without a connector, a long correct option
# is treated as legitimately detailed, not as a merge of distractors.
_COMBINED_CONNECTOR_TOKENS = {
    "and", "both", "all", "or",
    "va", "ca", "tat", "hoac", "deu",
}


def _strip_diacritics(text: str) -> str:
    import unicodedata
    # Vietnamese đ/Đ are atomic letters that NFKD does NOT decompose; map manually.
    text = text.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _normalize_for_match(text: str) -> str:
    """Lowercase, strip diacritics, collapse whitespace, drop trailing punctuation."""
    if not text:
        return ""
    stripped = _strip_diacritics(str(text)).lower()
    stripped = re.sub(r"[^\w\s]", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    return stripped


def _option_token_set(text: str) -> set:
    norm = _normalize_for_match(text)
    return set(re.findall(r"\w+", norm))


def _is_banned_phrase(option: str) -> bool:
    norm = _normalize_for_match(option)
    if not norm:
        return False
    if norm in _BANNED_OPTION_LITERALS_NORMALIZED:
        return True
    # Substring match for literal aggregators (handles trailing fragments).
    for literal in _BANNED_OPTION_LITERALS_NORMALIZED:
        if literal in norm:
            return True
    for pattern in _BANNED_OPTION_REGEXES:
        if pattern.search(option):
            return True
    return False


# Specific multi-word phrases that resolve to an "all_of_above" or
# "none_of_above" rejection. Each entry is matched as a whole-substring on the
# normalized option text. Bare single words ("tat ca", "deu dung") are NOT
# included on purpose — they generate too many false positives.
_ALL_OF_ABOVE_PHRASES = (
    "all of the above",
    "all the above",
    "all of these",
    "all answers are correct",
    "all of the answers are correct",
    "all three answers",
    "all four answers",
    "tat ca cac dap an tren",
    "tat ca dap an tren",
    "tat ca y tren",
    "tat ca cac y tren",
    "tat ca cac phuong an tren",
    "tat ca phuong an tren",
    "cac y tren deu dung",
    "cac dap an tren deu dung",
    "tat ca deu dung",
    "ca 3 dap an tren",
    "ca ba dap an tren",
    "ca hai dap an tren",
    "ca 2 dap an tren",
    "ca hai y tren",
    "ca ba y tren",
)

_NONE_OF_ABOVE_PHRASES = (
    "none of the above",
    "none of these",
    "no correct answer",
    "no answer is correct",
    "khong co dap an nao dung",
    "khong dap an nao dung",
    "khong co y nao dung",
    "khong y nao dung",
    "khong co phuong an nao dung",
    "deu sai het",
)


def _classify_banned_phrase(option: str) -> Optional[str]:
    """Return a specific rejection_reason for banned phrases, or None.

    Conservative: only triggers on explicit aggregator/meta patterns. Bare
    Vietnamese tokens like "tất cả", "cả hai", "đều đúng" are NOT enough on
    their own — the option must contain a recognizable meta phrase or an
    option-letter combination pattern.
    """
    norm = _normalize_for_match(option)
    if not norm:
        return None
    for phrase in _ALL_OF_ABOVE_PHRASES:
        if phrase in norm:
            return "all_of_above"
    for phrase in _NONE_OF_ABOVE_PHRASES:
        if phrase in norm:
            return "none_of_above"
    for pattern in _BANNED_OPTION_REGEXES:
        if pattern.search(option):
            return "combined_answer"
    return None


def _is_suspicious_meta_option(option: str) -> bool:
    """True only when the option contains a multi-word meta phrase.

    Single Vietnamese function words ("tất cả", "cả hai") are not enough — they
    appear in many legitimate options. We require a phrase that combines an
    aggregator with an above-style anchor.
    """
    norm = _normalize_for_match(option)
    if not norm:
        return False
    for phrase in _SUSPICIOUS_META_PHRASES_NORMALIZED:
        if phrase in norm:
            return True
    return False


def _is_combined_superset(option: str, others: List[str]) -> bool:
    """
    Conservative combined-superset check.

    Returns True only when ALL of the following hold:
      - the option contains an explicit connector token (and / both / cả / và / ...)
      - its token set strictly contains tokens from >= 2 distinct other options
      - each subsumed other option is meaningfully shorter than the candidate.

    A long correct option that does NOT contain a connector is treated as a
    legitimately detailed answer, not as a merger.
    """
    own = _option_token_set(option)
    if len(own) < 6:
        return False
    if not (own & _COMBINED_CONNECTOR_TOKENS):
        return False
    contained = 0
    for other in others:
        other_tokens = _option_token_set(other)
        if not other_tokens or other_tokens == own:
            continue
        # Require the other option to be substantially smaller and a strict subset.
        if other_tokens.issubset(own) and len(other_tokens) <= max(2, int(len(own) * 0.6)):
            contained += 1
    return contained >= 2


def _is_correct_length_outlier(
    options: List[str],
    correct_index: int,
    max_ratio: float = 1.8,
) -> bool:
    """
    True if the correct option is noticeably longer than every distractor
    by more than `max_ratio`x. Cheap proxy for length bias / option that
    gathers all the right ideas while distractors are short.
    """
    correct_len = max(1, len(options[correct_index].strip()))
    distractor_lens = [len(o.strip()) for i, o in enumerate(options) if i != correct_index]
    longest_distractor = max(distractor_lens) if distractor_lens else 0
    if longest_distractor == 0:
        return False
    return correct_len >= max_ratio * longest_distractor and (correct_len - longest_distractor) >= 25


def _semantic_duplicate_options(options: List[str], jaccard_threshold: float = 0.85) -> bool:
    """
    True if any two options have token-set Jaccard similarity >= threshold,
    indicating a paraphrase/duplicate that breaks single-best-answer.
    """
    token_sets = [_option_token_set(o) for o in options]
    for i in range(len(token_sets)):
        for j in range(i + 1, len(token_sets)):
            a, b = token_sets[i], token_sets[j]
            if not a or not b:
                continue
            jac = len(a & b) / len(a | b)
            if jac >= jaccard_threshold:
                return True
    return False


def validate_mcq_structure(
    question: str,
    options: List[str],
    correct_index: int,
) -> Tuple[bool, str]:
    """
    Conservative structural validation for a single MCQ.

    Returns ``(ok, rejection_reason)``. When ``ok`` is True, ``rejection_reason``
    is an empty string. When ``ok`` is False, ``rejection_reason`` is one of:

    - ``invalid_mcq_structure``     – malformed input (missing options / index)
    - ``all_of_above``              – explicit "all of the above" aggregator
    - ``none_of_above``             – explicit "none of the above" aggregator
    - ``combined_answer``           – "A and B" pattern OR superset+connector merge
    - ``suspicious_meta_option``    – multi-word meta phrase (rare)
    - ``semantic_duplicate_option`` – two options are near-paraphrases

    Note: option length bias is NO LONGER a hard reject (it produced too many
    false positives on legitimately detailed correct answers). Callers may
    inspect it separately via ``_is_correct_length_outlier`` for telemetry.
    """
    if not isinstance(options, list) or len(options) != 4:
        return False, "invalid_mcq_structure"
    if correct_index is None or not (0 <= correct_index < 4):
        return False, "invalid_mcq_structure"
    if any(not isinstance(o, str) or not o.strip() for o in options):
        return False, "invalid_mcq_structure"

    # 1. Explicit aggregator / combined-letter phrases (highest precision).
    for opt in options:
        reason = _classify_banned_phrase(opt)
        if reason:
            return False, reason

    # 2. Multi-word meta phrases (rare — single tokens are intentionally NOT enough).
    for opt in options:
        if _is_suspicious_meta_option(opt):
            return False, "suspicious_meta_option"

    # 3. Combined / superset options. Requires an explicit connector token to fire.
    for i, opt in enumerate(options):
        others = [o for j, o in enumerate(options) if j != i]
        if _is_combined_superset(opt, others):
            return False, "combined_answer"

    # 4. Semantic / lexical duplicate options.
    if _semantic_duplicate_options(options):
        return False, "semantic_duplicate_option"

    return True, ""


class QuizGenerator:
    """
    Generate quiz questions from documents using RAG.
    Supports multiple LLM providers with strict JSON output.
    """
    
    def __init__(
        self,
        retriever: DocumentRetriever,
        llm_provider: Optional[BaseLLM] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        base_url: Optional[str] = None,
        key_pool=None,
    ):
        """
        Initialize Quiz Generator.
        
        Args:
            retriever: DocumentRetriever instance
            llm_provider: Pre-configured LLM provider (if None, uses LLMFactory)
            model: Model name override (legacy, for backwards compatibility)
            temperature: Generation temperature (lower = more focused)
            base_url: API base URL (legacy)
            key_pool: Optional KeyPool for round-robin API key rotation
        """
        self.retriever = retriever
        self._key_pool = key_pool
        
        # Store legacy params for backwards compatibility
        self._model_override = model
        self._temperature_override = temperature if temperature is not None else 0.3
        self._base_url_override = base_url
        
        # Initialize LLM provider
        self._llm_provider: Optional[BaseLLM] = llm_provider
        
        # LLM instances (lazy initialized)
        self._llm = None  # Regular LLM
        self._llm_json = None  # JSON-mode LLM for quiz generation
        
        # Prompt templates
        self.prompt_vi = self._build_main_prompt("vi")
        self.prompt_en = self._build_main_prompt("en")
        self.supplement_prompt_vi = ChatPromptTemplate.from_template(QUIZ_SUPPLEMENT_PROMPT_VI_V2)
        self.supplement_prompt_en = ChatPromptTemplate.from_template(QUIZ_SUPPLEMENT_PROMPT_EN_V2)
        self.blueprint_prompt_vi = ChatPromptTemplate.from_template(QUIZ_SLOT_BLUEPRINT_PROMPT_VI)
        self.blueprint_prompt_en = ChatPromptTemplate.from_template(QUIZ_SLOT_BLUEPRINT_PROMPT_EN)
        
        # Initialize if provider not passed
        if self._llm_provider is None:
            self._init_llm()
        
        logger.info(f"QuizGenerator initialized with provider: {self._llm_provider.provider_name}")

    def _build_main_prompt(self, language: str, reduced: bool = False) -> ChatPromptTemplate:
        """Build the main generation prompt for slot-based exact-count generation."""
        base = QUIZ_GENERATION_PROMPT_VNEXT_VI if language == "vi" else QUIZ_GENERATION_PROMPT_VNEXT_EN
        return ChatPromptTemplate.from_template(base)

    @staticmethod
    def _context_budgets(num_questions: int) -> Tuple[int, int]:
        """Backward-compatible wrapper for raw pool and batch context budgets."""
        return (
            QuizGenerator._raw_pool_budget(num_questions),
            QuizGenerator._batch_context_window(min(10, num_questions)),
        )

    @staticmethod
    def _raw_pool_budget(num_questions: int) -> int:
        if num_questions <= 10:
            return 16
        if num_questions <= 20:
            return 32
        if num_questions <= 35:
            return 56
        return 80

    @staticmethod
    def _batch_context_window(batch_size: int) -> int:
        return 12 if batch_size <= 8 else 14

    @staticmethod
    def _plan_batch_sizes(num_questions: int) -> List[int]:
        if num_questions <= 15:
            return [num_questions]
        if num_questions <= 30:
            first = (num_questions + 1) // 2
            return [first, num_questions - first]
        batch_count = max(3, math.ceil(num_questions / 15))
        base_size = num_questions // batch_count
        remainder = num_questions % batch_count
        return [
            base_size + (1 if index < remainder else 0)
            for index in range(batch_count)
            if base_size + (1 if index < remainder else 0) > 0
        ]

    @staticmethod
    def _is_large_request(num_questions: int) -> bool:
        return num_questions >= LARGE_REQUEST_QUESTION_THRESHOLD

    @staticmethod
    def _plan_topic_group_batches(
        slots: List[Dict[str, Any]],
        max_batch: int = 15,
        min_batch: int = 5,
    ) -> List[List[Dict[str, Any]]]:
        """Group *slots* by ``topic_group`` then split large groups.

        Each batch targets a single topic group so the LLM context can be
        narrowly focused.  Groups with more than *max_batch* slots are split
        into sub-batches.  Very small groups (< min_batch) are merged with
        the next small group if possible.
        """
        from collections import OrderedDict

        groups: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
        for slot in slots:
            gid = slot.get("topic_group", "G1")
            groups.setdefault(gid, []).append(slot)

        raw_batches: List[List[Dict[str, Any]]] = []
        for _gid, group_slots in groups.items():
            if len(group_slots) <= max_batch:
                raw_batches.append(group_slots)
            else:
                # Split large group into sub-batches
                count = math.ceil(len(group_slots) / max_batch)
                base = len(group_slots) // count
                rem = len(group_slots) % count
                offset = 0
                for i in range(count):
                    size = base + (1 if i < rem else 0)
                    raw_batches.append(group_slots[offset:offset + size])
                    offset += size

        # Merge tiny trailing batches when possible
        merged: List[List[Dict[str, Any]]] = []
        for batch in raw_batches:
            if merged and len(merged[-1]) < min_batch and len(merged[-1]) + len(batch) <= max_batch:
                merged[-1].extend(batch)
            else:
                merged.append(list(batch))

        # Fallback: if somehow empty, return all slots as one batch
        return merged if merged else [list(slots)]

    @staticmethod
    def _should_skip_blueprint_for_request(num_questions: int, topics: List[str]) -> bool:
        """Blueprint is now always allowed; chunked blueprint handles large requests."""
        return False

    @staticmethod
    def _max_total_llm_calls(num_questions: int, blueprint_attempted: bool) -> Optional[int]:
        if not QuizGenerator._is_large_request(num_questions):
            return None
        return (
            MAX_LLM_CALLS_PER_LARGE_QUIZ_WITH_BLUEPRINT
            if blueprint_attempted
            else MAX_LLM_CALLS_PER_LARGE_QUIZ_NO_BLUEPRINT
        )

    @staticmethod
    def _max_generation_calls(num_questions: int) -> Optional[int]:
        if not QuizGenerator._is_large_request(num_questions):
            return None
        return MAX_LLM_CALLS_PER_LARGE_QUIZ_NO_BLUEPRINT

    @staticmethod
    def _max_est_completion_tokens(num_questions: int) -> Optional[int]:
        if not QuizGenerator._is_large_request(num_questions):
            return None
        return MAX_EST_COMPLETION_TOKENS_PER_LARGE_QUIZ

    @staticmethod
    def _should_run_second_refill(num_questions: int, remaining_slot_count: int) -> bool:
        if remaining_slot_count <= 0:
            return False
        return remaining_slot_count <= min(8, math.ceil(num_questions * 0.2))

    @staticmethod
    def _partial_success_threshold(num_questions: int) -> int:
        return math.ceil(num_questions * PARTIAL_SUCCESS_RATIO)

    @staticmethod
    def _is_partial_success(num_questions: int, generated_count: int) -> bool:
        return (
            generated_count < num_questions
            and generated_count >= QuizGenerator._partial_success_threshold(num_questions)
        )

    def _build_user_facing_shortfall_message(
        self,
        *,
        num_questions: int,
        final_count: int,
        blueprint_skip_reason: Optional[str],
        plan_stats: Optional[Dict[str, Any]],
        remaining_slots: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        missing_count = max(0, num_questions - final_count)
        plan_stats = plan_stats or {}
        rejected_by_structure = int(plan_stats.get("rejected_by_structure_count") or 0)

        # When the shortfall is driven by structural validation rejections we
        # surface a neutral message instead of blaming the source material.
        if missing_count > 0 and rejected_by_structure >= missing_count:
            return (
                f"Đã tạo được {final_count}/{num_questions} câu hỏi hợp lệ sau kiểm tra chất lượng. "
                f"Một số câu bị loại do chưa đạt tiêu chí cấu trúc đáp án."
            )

        message_parts = [f"Đã tạo {final_count}/{num_questions} câu hỏi, thiếu {missing_count} câu."]
        reasons: List[str] = []

        if plan_stats.get("budget_cap_hit"):
            reasons.append("Hệ thống đã dừng ở mức chi phí an toàn để tránh tốn quá nhiều token.")

        if blueprint_skip_reason in {
            "blueprint skipped due to large request",
            "blueprint skipped due to length limit",
        }:
            reasons.append("Yêu cầu lớn nên hệ thống dùng chế độ tiết kiệm token, có thể thiếu một vài câu hỏi.")

        # Mention structural rejections only as a partial explanation when they
        # don't fully account for the shortfall (otherwise the early return above
        # already handled it).
        if rejected_by_structure > 0:
            reasons.append(
                f"Một số câu ({rejected_by_structure}) bị loại ở bước kiểm tra cấu trúc đáp án."
            )
        elif remaining_slots:
            reasons.append("Một số góc hỏi chưa tìm được đủ căn cứ trong tài liệu.")

        if not reasons and blueprint_skip_reason == "blueprint skipped due to parse/generation fallback":
            reasons.append("Hệ thống đã rút gọn bước lập kế hoạch để giữ kết quả ổn định.")

        if not reasons and missing_count > 0:
            reasons.append("Một số câu hỏi được lược bớt để giữ độ bám sát với tài liệu.")

        if reasons:
            message_parts.append(" ".join(reasons[:2]))

        return " ".join(message_parts)

    @staticmethod
    def _existing_question_prompt_budget(
        generation_mode: str,
        cost_protected: bool,
    ) -> Tuple[int, int]:
        if generation_mode == "global_refill_2":
            return (5, 750) if cost_protected else (6, 900)
        if generation_mode.startswith("global_refill"):
            return (6, 900) if cost_protected else (8, 1200)
        if cost_protected:
            return (8, 1200)
        return (12, 1600)

    @staticmethod
    def _context_window_for_mode(
        batch_size: int,
        generation_mode: str,
        cost_protected: bool,
    ) -> int:
        base_budget = QuizGenerator._batch_context_window(batch_size)
        if generation_mode == "global_refill_2":
            return min(base_budget, 7 if cost_protected else 8)
        if generation_mode.startswith("global_refill"):
            return min(base_budget, 8 if cost_protected else 10)
        if cost_protected:
            return min(base_budget, 10)
        return base_budget

    @staticmethod
    def _max_tokens_for_generation_pass(
        batch_target: int,
        generation_mode: str,
        cost_protected: bool,
    ) -> int:
        if cost_protected:
            if generation_mode == "global_refill_2":
                return max(1300, min(2200, 650 + batch_target * 110))
            if generation_mode.startswith("global_refill"):
                return max(1500, min(2400, 700 + batch_target * 120))
            return max(1800, min(2800, 900 + batch_target * 140))

        return max(2048, min(6144, 700 + batch_target * 250))

    @staticmethod
    def _is_length_limit_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "length limit" in message
            or "length_limit" in message
            or "length was reached" in message
        )

    @staticmethod
    def _default_blueprint_section() -> str:
        return "No external coverage plan provided. Build a balanced grounded coverage plan from the source material."
    
    def _init_llm(self):
        """Initialize LLM using factory."""
        kwargs = {"temperature": self._temperature_override}
        if self._base_url_override:
            kwargs["base_url"] = self._base_url_override
        
        self._llm_provider = LLMFactory.create(
            model=self._model_override,
            **kwargs
        )
    
    @property
    def llm(self):
        """Get regular LLM instance (lazy initialization)."""
        if self._llm is None:
            self._llm = self._llm_provider.get_llm(json_mode=False)
        return self._llm
    
    @property
    def llm_json(self):
        """Get JSON-mode LLM instance for quiz generation (lazy initialization)."""
        if self._llm_json is None:
            self._llm_json = self._llm_provider.get_llm(json_mode=True)
        return self._llm_json
    
    @property
    def model(self) -> str:
        """Get current model name."""
        return self._llm_provider.model if self._llm_provider else self._model_override or rag_config.GROQ_MODEL
    
    def set_llm_provider(self, provider: BaseLLM):
        """
        Set a new LLM provider at runtime.
        
        Args:
            provider: New LLM provider instance
        """
        self._llm_provider = provider
        self._llm = None  # Reset cached instances
        self._llm_json = None
        logger.info(f"QuizGenerator LLM provider updated: {provider.provider_name}")
    
    def extract_topics_from_context(
        self,
        context: str,
        max_topics: int = 10
    ) -> Dict[str, Any]:
        """
        Extract topics from provided context using LLM.
        Used during document indexing to extract and cache topics.
        
        Args:
            context: Document content to analyze
            max_topics: Maximum number of topics to extract
            
        Returns:
            Dictionary with topics
        """
        logger.info("Extracting topics from provided context...")
        
        try:
            topic_prompt = ChatPromptTemplate.from_template("""Analyze the following document content and extract the main topics/concepts that could be used for quiz generation.

DOCUMENT CONTENT:
{context}

Extract {max_topics} main topics from this content. Topics should be:
- Specific enough to generate focused questions
- Clear and concise (1-5 words each)
- Represent key concepts, chapters, or sections in the document
- In the same language as the document content

OUTPUT FORMAT (JSON only):
{{
  "topics": [
    {{"name": "Topic Name", "description": "Brief description of what this topic covers"}}
  ]
}}

Return ONLY valid JSON, no additional text.""")
            
            # Use JSON-mode LLM for reliable JSON output
            chain = topic_prompt | self.llm_json
            
            response = chain.invoke({
                "context": context,
                "max_topics": max_topics
            })
            
            content = response.content if hasattr(response, 'content') else str(response)
            logger.info(f"Topic extraction response: {content[:300]}...")
            
            data = self._parse_quiz_response(content)
            
            if data and data.get("topics"):
                return {
                    "success": True,
                    "topics": data["topics"]
                }
            
            return {
                "success": False,
                "topics": [],
                "message": "Could not extract topics"
            }
            
        except Exception as e:
            logger.error(f"Error extracting topics from context: {e}")
            return {
                "success": False,
                "topics": [],
                "message": str(e)
            }
    
    def extract_topics(self, max_topics: int = 10) -> Dict[str, Any]:
        """
        Extract suggested topics from indexed documents using LLM.
        
        Args:
            max_topics: Maximum number of topics to suggest
            
        Returns:
            Dictionary with topics and metadata
        """
        logger.info("Extracting topics from documents...")
        
        try:
            # Get sample documents for topic extraction
            documents = self.retriever.vector_store.get_all_document_content(max_docs=20)
            
            if not documents:
                return {
                    "success": False,
                    "topics": [],
                    "message": "Chưa có tài liệu nào được index"
                }
            
            # Create context from documents
            context = "\n\n---\n\n".join(documents[:15])  # Limit to avoid token overflow
            
            # Prompt for topic extraction - use JSON mode LLM
            topic_prompt = ChatPromptTemplate.from_template("""Analyze the following document content and extract the main topics/concepts that could be used for quiz generation.

DOCUMENT CONTENT:
{context}

Extract {max_topics} main topics from this content. Topics should be:
- Specific enough to generate focused questions
- Clear and concise (1-5 words each)
- Represent key concepts, chapters, or sections in the document

OUTPUT FORMAT (JSON only):
{{
  "topics": [
    {{"name": "Topic Name", "description": "Brief description of what this topic covers"}}
  ]
}}

Return ONLY valid JSON, no additional text.""")
            
            chain = topic_prompt | self.llm_json
            
            response = chain.invoke({
                "context": context[:8000],  # Limit context size
                "max_topics": max_topics
            })
            
            content = response.content if hasattr(response, 'content') else str(response)
            logger.info(f"Topic extraction response: {content[:300]}...")
            
            # Parse response
            data = self._parse_quiz_response(content)
            
            if data and data.get("topics"):
                topics = data["topics"]
                logger.info(f"Extracted {len(topics)} topics")
                return {
                    "success": True,
                    "topics": topics,
                    "message": ""
                }
            
            return {
                "success": False,
                "topics": [],
                "message": "Không thể trích xuất chủ đề từ tài liệu"
            }
            
        except Exception as e:
            logger.error(f"Error extracting topics: {e}")
            return {
                "success": False,
                "topics": [],
                "message": f"Lỗi: {str(e)}"
            }

    @staticmethod
    def _normalize_text(value: Any) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip()).lower()

    @staticmethod
    def _tokenize_text(text: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-zA-Z0-9_]+", text.lower())
            if len(token) > 2
        }

    @staticmethod
    def _jaccard_similarity(left: set[str], right: set[str]) -> float:
        if not left and not right:
            return 1.0
        if not left or not right:
            return 0.0
        union = left | right
        return len(left & right) / max(1, len(union))

    def _document_signature(self, doc: Document) -> str:
        source = doc.metadata.get("source", "unknown")
        page = doc.metadata.get("page", "?")
        content = self._normalize_text(doc.page_content)[:600]
        return f"{source}|{page}|{content}"

    def _dedupe_documents(self, documents: Iterable[Document]) -> List[Document]:
        seen = set()
        unique: List[Document] = []

        for index, doc in enumerate(documents):
            signature = self._document_signature(doc)
            if signature in seen:
                continue
            seen.add(signature)
            doc.metadata.setdefault("_raw_rank", index)
            unique.append(doc)

        return unique

    def _annotate_documents(self, documents: List[Document], retrieval_topic: Optional[str] = None) -> List[Document]:
        for index, doc in enumerate(documents):
            doc.metadata.setdefault("_raw_rank", index)
            if retrieval_topic:
                doc.metadata["retrieval_topic"] = retrieval_topic
        return documents

    def _retrieve_documents_with_budget(
        self,
        query: str,
        max_total_docs: int,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        hash_to_collection_name: Optional[Dict[str, str]] = None,
        # ---- V1 course-level domain knowledge extensions ----
        roles_by_hash: Optional[Dict[str, str]] = None,
        language_by_hash: Optional[Dict[str, str]] = None,
        topic_language: Optional[str] = None,
        domain_quota_ratio: Optional[float] = None,
        translation_cache: Optional[Dict[str, str]] = None,
        llm_for_translation: Optional[Any] = None,
    ) -> List[Document]:
        max_total_docs = max(1, max_total_docs)

        if hasattr(self.retriever, "retrieve_with_budget"):
            extra_kwargs: Dict[str, Any] = {}
            if roles_by_hash is not None:
                extra_kwargs["roles_by_hash"] = roles_by_hash
            if language_by_hash is not None:
                extra_kwargs["language_by_hash"] = language_by_hash
            if topic_language is not None:
                extra_kwargs["topic_language"] = topic_language
            if domain_quota_ratio is not None:
                extra_kwargs["domain_quota_ratio"] = domain_quota_ratio
            if translation_cache is not None:
                extra_kwargs["translation_cache"] = translation_cache
            if llm_for_translation is not None:
                extra_kwargs["llm_for_translation"] = llm_for_translation
            try:
                return self.retriever.retrieve_with_budget(
                    query=query,
                    max_total_docs=max_total_docs,
                    target_file_hashes=target_file_hashes,
                    user_id=user_id,
                    hash_to_collection_name=hash_to_collection_name,
                    **extra_kwargs,
                )
            except TypeError:
                # Older retriever signature (no V1 kwargs) — retry without.
                return self.retriever.retrieve_with_budget(
                    query=query,
                    max_total_docs=max_total_docs,
                    target_file_hashes=target_file_hashes,
                    user_id=user_id,
                    hash_to_collection_name=hash_to_collection_name,
                )

        retrieve_kwargs: Dict[str, Any] = {"k": max_total_docs}
        if hasattr(self.retriever, "resolve_target_file_hashes"):
            retrieve_kwargs["target_file_hashes"] = target_file_hashes
            retrieve_kwargs["user_id"] = user_id
            if hash_to_collection_name:
                retrieve_kwargs["hash_to_collection_name"] = hash_to_collection_name
        return self.retriever.retrieve(query, **retrieve_kwargs)

    def _format_context_documents(self, documents: List[Document]) -> str:
        if self.retriever and hasattr(self.retriever, "format_context"):
            return self.retriever.format_context(documents)
        return format_context_documents(documents)

    def _extract_document_citations(self, documents: List[Document]) -> List[Dict[str, Any]]:
        if self.retriever and hasattr(self.retriever, "extract_citations"):
            return self.retriever.extract_citations(documents)
        return extract_document_citations(documents)

    def _select_context_documents(
        self,
        documents: List[Document],
        topics: List[str],
        final_budget: int,
    ) -> List[Document]:
        unique_documents = self._dedupe_documents(documents)
        if len(unique_documents) <= final_budget:
            return unique_documents

        selected: List[Document] = []
        remaining = unique_documents[:]
        topic_terms = self._tokenize_text(" ".join(topics))
        selected_sources: set[str] = set()
        selected_topics: set[str] = set()

        while remaining and len(selected) < final_budget:
            best_doc = None
            best_score = float("-inf")

            for candidate in remaining:
                candidate_tokens = self._tokenize_text(candidate.page_content)
                topic_overlap = (
                    len(candidate_tokens & topic_terms) / max(1, len(topic_terms))
                    if topic_terms else 0.0
                )
                novelty = 1.0
                if selected:
                    novelty = 1.0 - max(
                        self._jaccard_similarity(
                            candidate_tokens,
                            self._tokenize_text(chosen.page_content),
                        )
                        for chosen in selected
                    )

                source_key = candidate.metadata.get("file_hash") or candidate.metadata.get("source")
                source_bonus = 0.25 if source_key not in selected_sources else 0.0

                retrieval_topic = candidate.metadata.get("retrieval_topic")
                topic_bonus = 0.35 if retrieval_topic and retrieval_topic not in selected_topics else 0.0

                raw_rank = int(candidate.metadata.get("_raw_rank", 9999))
                relevance_bonus = 1.0 / (1.0 + raw_rank)

                score = (novelty * 1.4) + (topic_overlap * 1.1) + source_bonus + topic_bonus + (relevance_bonus * 0.25)
                if score > best_score:
                    best_score = score
                    best_doc = candidate

            if best_doc is None:
                break

            remaining.remove(best_doc)
            selected.append(best_doc)
            source_key = best_doc.metadata.get("file_hash") or best_doc.metadata.get("source")
            selected_sources.add(source_key)
            retrieval_topic = best_doc.metadata.get("retrieval_topic")
            if retrieval_topic:
                selected_topics.add(retrieval_topic)

        return selected

    def _allocate_topic_budgets(
        self,
        topics: List[str],
        raw_budget: int,
        target_file_hashes: Optional[List[str]],
        user_id: Optional[str],
    ) -> Dict[str, int]:
        if not topics:
            return {}

        if len(topics) > raw_budget:
            budgets = {
                topic: (1 if index < raw_budget else 0)
                for index, topic in enumerate(topics)
            }
            return budgets

        min_per_topic = 4 if raw_budget >= len(topics) * 4 else max(1, raw_budget // max(1, len(topics)))
        budgets = {topic: min_per_topic for topic in topics}
        coverage_counts: Dict[str, int] = {}

        for topic in topics:
            if budgets[topic] <= 0:
                coverage_counts[topic] = 0
                continue
            sample_docs = self._retrieve_documents_with_budget(
                query=topic,
                max_total_docs=max(1, min_per_topic),
                target_file_hashes=target_file_hashes,
                user_id=user_id,
            )
            coverage_counts[topic] = len(self._dedupe_documents(sample_docs))

        remaining = max(0, raw_budget - sum(budgets.values()))
        while remaining > 0:
            target_topic = min(topics, key=lambda item: (coverage_counts.get(item, 0), budgets[item]))
            budgets[target_topic] += 1
            coverage_counts[target_topic] = coverage_counts.get(target_topic, 0) + 1
            remaining -= 1

        return budgets

    def _should_use_blueprint(
        self,
        num_questions: int,
        topics: List[str],
        raw_document_count: int,
        final_budget: int,
    ) -> bool:
        """Always use blueprint for multi-topic or larger quizzes."""
        normalized_topics = [
            re.sub(r"\s+", " ", str(topic or "").strip())
            for topic in topics
            if str(topic or "").strip()
        ]
        if num_questions >= 10:
            return True
        if len(normalized_topics) > 1:
            return True
        return raw_document_count > final_budget

    def _build_blueprint(
        self,
        context: str,
        topic: str,
        difficulty: str,
        language: str,
        num_questions: int,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        prompt = self.blueprint_prompt_vi if language == "vi" else self.blueprint_prompt_en
        max_tokens = max(1000, min(1800, 400 + (num_questions * 28)))
        llm_json = self._llm_provider.get_llm(json_mode=True, max_tokens=max_tokens)
        chain = prompt | llm_json

        try:
            policy = DIFFICULTY_POLICIES.get(difficulty, DIFFICULTY_POLICIES["medium"])
            response = chain.invoke({
                "context": context,
                "topic": topic,
                "difficulty": difficulty,
                "difficulty_policy": policy["blueprint_instruction"],
                "num_questions": num_questions,
            })
            content = response.content if hasattr(response, "content") else str(response)
            blueprint_data = self._parse_quiz_response(content)
            if blueprint_data:
                return self._normalize_blueprint(
                    blueprint=blueprint_data,
                    topic=topic,
                    num_questions=num_questions,
                    difficulty=difficulty,
                ), None
            logger.warning("Blueprint generation returned unparseable content; falling back to local slot planner")
            failure_reason = "parse_failed"
        except Exception as exc:
            logger.warning("Blueprint generation failed: %s", exc)
            failure_reason = "length_limit" if self._is_length_limit_error(exc) else "generation_error"

        return self._normalize_blueprint(
            blueprint={},
            topic=topic,
            num_questions=num_questions,
            difficulty=difficulty,
        ), failure_reason

    def _build_blueprint_chunked(
        self,
        context: str,
        topic: str,
        difficulty: str,
        language: str,
        num_questions: int,
        topics: Optional[List[str]] = None,
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Build a blueprint in chunks for large quizzes.

        When *num_questions* exceeds ``BLUEPRINT_CHUNK_SIZE`` the request is
        split into several smaller calls whose results are merged and
        re-normalized to the required total.  For small requests this simply
        delegates to ``_build_blueprint``.
        """
        if num_questions <= BLUEPRINT_CHUNK_SIZE:
            return self._build_blueprint(context, topic, difficulty, language, num_questions)

        # Split the total into roughly-equal chunks capped at BLUEPRINT_CHUNK_SIZE
        chunk_count = math.ceil(num_questions / BLUEPRINT_CHUNK_SIZE)
        base = num_questions // chunk_count
        remainder = num_questions % chunk_count
        chunk_sizes = [
            base + (1 if i < remainder else 0)
            for i in range(chunk_count)
        ]

        merged_groups: List[Dict[str, Any]] = []
        merged_slots: List[Dict[str, Any]] = []
        seen_group_ids: set = set()
        last_failure: Optional[str] = None

        for chunk_idx, chunk_size in enumerate(chunk_sizes):
            chunk_blueprint, failure = self._build_blueprint(
                context, topic, difficulty, language, chunk_size,
            )
            if failure:
                last_failure = failure

            # Merge topic_groups (deduplicate by group_id)
            for group in chunk_blueprint.get("topic_groups", []):
                gid = group["group_id"]
                if gid not in seen_group_ids:
                    seen_group_ids.add(gid)
                    merged_groups.append(group)

            # Merge slots (re-number later)
            merged_slots.extend(chunk_blueprint.get("slots", []))

        # Re-normalize so we get exactly num_questions slots
        merged_raw = {
            "topic_groups": merged_groups,
            "slots": merged_slots[:num_questions],
            "notes": "",
        }
        normalized = self._normalize_blueprint(
            blueprint=merged_raw,
            topic=topic,
            num_questions=num_questions,
            difficulty=difficulty,
        )
        logger.info(
            "Chunked blueprint: %d chunks, %d groups, %d slots (target=%d)",
            chunk_count, len(normalized.get("topic_groups", [])),
            len(normalized.get("slots", [])), num_questions,
        )
        return normalized, last_failure

    def _format_blueprint_section(self, blueprint: Optional[Dict[str, Any]]) -> str:
        if not blueprint or not blueprint.get("slots"):
            return self._default_blueprint_section()

        lines = ["Use this slot plan as coverage guidance only. It is NOT draft quiz text."]
        for index, item in enumerate(blueprint.get("slots", []), start=1):
            evidence_refs = ", ".join(item.get("evidence_refs", [])[:3]) or "Document evidence not specified"
            lines.append(
                f"{index}. slot={item.get('slot_id', f'S{index:02d}')}; "
                f"group={item.get('topic_group_label', item.get('topic_group', 'G1'))}; "
                f"coverage={item.get('coverage_item', 'supported concept')}; "
                f"support={item.get('support_level', 'direct_source')}; "
                f"form={item.get('question_form', 'definition')}; "
                f"trap={item.get('trap_type', 'near_miss')}; "
                f"refs={evidence_refs}"
            )
        notes = blueprint.get("notes")
        if notes:
            lines.append(f"Notes: {notes}")
        return "\n".join(lines)

    def _fallback_topic_groups(self, requested_topics: List[str]) -> List[Dict[str, Any]]:
        unique_topics: List[str] = []
        seen = set()
        for topic in requested_topics or ["General"]:
            label = re.sub(r"\s+", " ", str(topic or "").strip())
            if not label:
                continue
            normalized = self._normalize_text(label)
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_topics.append(label)

        if not unique_topics:
            unique_topics = ["General"]

        return [
            {
                "group_id": f"G{index + 1}",
                "label": topic,
                "source_topics": [topic],
                "evidence_refs": [],
            }
            for index, topic in enumerate(unique_topics)
        ]

    def _compute_group_targets(self, groups: List[Dict[str, Any]], num_questions: int) -> Dict[str, int]:
        if not groups:
            return {}

        minimum = 2 if num_questions >= len(groups) * 2 else 1
        targets = {group["group_id"]: minimum for group in groups}
        remaining = max(0, num_questions - sum(targets.values()))
        ranking = sorted(
            groups,
            key=lambda group: (
                -(len(group.get("evidence_refs", [])) + len(group.get("source_topics", []))),
                group["group_id"],
            ),
        )

        while remaining > 0:
            for group in ranking:
                if remaining <= 0:
                    break
                targets[group["group_id"]] += 1
                remaining -= 1

        return targets

    def _build_fallback_slot(
        self,
        slot_index: int,
        group: Dict[str, Any],
        ordinal: int,
        support_level: Optional[str] = None,
        difficulty: str = "medium",
    ) -> Dict[str, Any]:
        policy = DIFFICULTY_POLICIES.get(difficulty, DIFFICULTY_POLICIES["medium"])
        forms = policy["preferred_question_forms"]
        traps = policy["allowed_trap_types"]
        levels = policy["allowed_support_levels"]
        slot_number = slot_index + 1
        return {
            "slot_id": f"S{slot_number:02d}",
            "topic_group": group["group_id"],
            "topic_group_label": group["label"],
            "source_topics": group.get("source_topics", [group["label"]]),
            "coverage_item": group["label"] if ordinal == 0 else f"{group['label']} focus {ordinal + 1}",
            "support_level": support_level or levels[slot_index % len(levels)],
            "question_form": forms[slot_index % len(forms)],
            "trap_type": traps[(slot_index + ordinal) % len(traps)],
            "evidence_refs": group.get("evidence_refs", [])[:3],
        }

    def _normalize_blueprint(
        self,
        blueprint: Dict[str, Any],
        topic: str,
        num_questions: int,
        difficulty: str = "medium",
    ) -> Dict[str, Any]:
        policy = DIFFICULTY_POLICIES.get(difficulty, DIFFICULTY_POLICIES["medium"])
        allowed_levels = set(policy["allowed_support_levels"])
        allowed_forms = set(policy["allowed_question_forms"])
        allowed_traps = set(policy["allowed_trap_types"])
        preferred_forms = policy["preferred_question_forms"]
        requested_topics = [
            segment.strip()
            for segment in re.split(r"[,;\n]", topic)
            if segment.strip()
        ]
        fallback_groups = self._fallback_topic_groups(requested_topics)

        raw_groups = blueprint.get("topic_groups") if isinstance(blueprint.get("topic_groups"), list) else []
        topic_groups: List[Dict[str, Any]] = []
        for index, raw_group in enumerate(raw_groups):
            if not isinstance(raw_group, dict):
                continue
            group_id = str(raw_group.get("group_id") or f"G{index + 1}").strip() or f"G{index + 1}"
            label = re.sub(r"\s+", " ", str(raw_group.get("label") or "").strip()) or f"Topic Group {index + 1}"
            source_topics = [
                re.sub(r"\s+", " ", str(item).strip())
                for item in raw_group.get("source_topics", [])
                if str(item).strip()
            ] or [label]
            evidence_refs = [
                re.sub(r"\s+", " ", str(item).strip())
                for item in raw_group.get("evidence_refs", [])
                if str(item).strip()
            ][:3]
            topic_groups.append({
                "group_id": group_id,
                "label": label,
                "source_topics": source_topics,
                "evidence_refs": evidence_refs,
            })

        if not topic_groups:
            topic_groups = fallback_groups

        groups_by_id = {group["group_id"]: group for group in topic_groups}
        group_targets = self._compute_group_targets(topic_groups, num_questions)
        slots: List[Dict[str, Any]] = []
        group_counts = {group["group_id"]: 0 for group in topic_groups}
        raw_slots = blueprint.get("slots") if isinstance(blueprint.get("slots"), list) else []

        for raw_slot in raw_slots:
            if len(slots) >= num_questions or not isinstance(raw_slot, dict):
                break

            topic_group = str(raw_slot.get("topic_group") or "").strip()
            if topic_group not in groups_by_id:
                topic_group = topic_groups[len(slots) % len(topic_groups)]["group_id"]
            group = groups_by_id[topic_group]

            support_level = str(raw_slot.get("support_level") or "").strip()
            if support_level not in allowed_levels:
                support_level = policy["allowed_support_levels"][len(slots) % len(policy["allowed_support_levels"])]

            question_form = str(raw_slot.get("question_form") or "").strip()
            if question_form not in allowed_forms:
                question_form = preferred_forms[len(slots) % len(preferred_forms)]

            trap_type = str(raw_slot.get("trap_type") or "").strip()
            if trap_type not in allowed_traps:
                trap_type = policy["allowed_trap_types"][len(slots) % len(policy["allowed_trap_types"])]

            coverage_item = re.sub(r"\s+", " ", str(raw_slot.get("coverage_item") or "").strip()) or group["label"]
            evidence_refs = [
                re.sub(r"\s+", " ", str(item).strip())
                for item in raw_slot.get("evidence_refs", [])
                if str(item).strip()
            ][:3] or group.get("evidence_refs", [])[:3]

            group_counts[topic_group] += 1
            slots.append({
                "slot_id": f"S{len(slots) + 1:02d}",
                "topic_group": topic_group,
                "topic_group_label": group["label"],
                "source_topics": group.get("source_topics", [group["label"]]),
                "coverage_item": coverage_item,
                "support_level": support_level,
                "question_form": question_form,
                "trap_type": trap_type,
                "evidence_refs": evidence_refs,
            })

        while len(slots) < num_questions:
            target_group = min(
                topic_groups,
                key=lambda group: (
                    group_counts[group["group_id"]] - group_targets[group["group_id"]],
                    group_counts[group["group_id"]],
                    group["group_id"],
                ),
            )
            ordinal = group_counts[target_group["group_id"]]
            slots.append(self._build_fallback_slot(len(slots), target_group, ordinal, difficulty=difficulty))
            group_counts[target_group["group_id"]] += 1

        return {
            "topic_groups": topic_groups,
            "slots": slots[:num_questions],
            "notes": blueprint.get("notes", ""),
        }

    def _format_slot_section(self, slots: List[Dict[str, Any]]) -> str:
        if not slots:
            return "No slots assigned."

        lines = []
        for slot in slots:
            evidence_refs = ", ".join(slot.get("evidence_refs", [])[:3]) or "No explicit evidence refs"
            source_topics = ", ".join(slot.get("source_topics", [])[:3]) or slot.get("topic_group_label", slot.get("topic_group", ""))
            lines.append(
                f"{slot['slot_id']}: group={slot.get('topic_group_label', slot.get('topic_group'))}; "
                f"source_topics={source_topics}; "
                f"coverage={slot.get('coverage_item', 'supported concept')}; "
                f"support={slot.get('support_level', 'direct_source')}; "
                f"form={slot.get('question_form', 'definition')}; "
                f"trap={slot.get('trap_type', 'near_miss')}; "
                f"refs={evidence_refs}"
            )
        return "\n".join(lines)

    def _format_existing_questions_for_prompt(
        self,
        questions: List[Dict[str, Any]],
        max_items: int = 12,
        max_chars: int = 1600,
    ) -> str:
        if not questions:
            return "None yet."

        recent_questions = questions[-max_items:]
        lines: List[str] = []

        omitted_count = max(0, len(questions) - len(recent_questions))
        if omitted_count:
            lines.append(
                f"... {omitted_count} earlier questions omitted for prompt budget. "
                "Still avoid repeating their concepts."
            )

        recent_lines: List[str] = []
        for reverse_index, question in enumerate(reversed(recent_questions), start=1):
            index = len(questions) - reverse_index + 1
            question_text = re.sub(r"\s+", " ", str(question.get("question") or "").strip())
            if not question_text:
                continue
            line = f"{index}. {question_text}"
            projected = len("\n".join(lines + list(reversed(recent_lines + [line]))))
            if recent_lines and projected > max_chars:
                recent_lines.append("... additional recent questions omitted for prompt budget.")
                break
            recent_lines.append(line)

        lines.extend(reversed(recent_lines))

        return "\n".join(lines) or "None yet."

    def _select_batch_context_documents(
        self,
        documents: List[Document],
        batch_slots: List[Dict[str, Any]],
        budget_override: Optional[int] = None,
    ) -> List[Document]:
        unique_documents = self._dedupe_documents(documents)
        budget = budget_override or self._batch_context_window(len(batch_slots))
        if len(unique_documents) <= budget:
            return unique_documents

        slot_terms = set()
        topic_terms = set()
        for slot in batch_slots:
            slot_terms |= self._tokenize_text(slot.get("coverage_item", ""))
            topic_terms |= self._tokenize_text(slot.get("topic_group_label", ""))
            for source_topic in slot.get("source_topics", []):
                topic_terms |= self._tokenize_text(source_topic)

        selected: List[Document] = []
        remaining = unique_documents[:]
        selected_sources: set[str] = set()
        selected_pages: set[Tuple[str, Any]] = set()
        normalized_requested_topics = {
            self._normalize_text(topic)
            for slot in batch_slots
            for topic in slot.get("source_topics", [])
        }

        while remaining and len(selected) < budget:
            best_doc = None
            best_score = float("-inf")

            for candidate in remaining:
                candidate_tokens = self._tokenize_text(candidate.page_content)
                coverage_overlap = (
                    len(candidate_tokens & slot_terms) / max(1, len(slot_terms))
                    if slot_terms else 0.0
                )
                topic_overlap = (
                    len(candidate_tokens & topic_terms) / max(1, len(topic_terms))
                    if topic_terms else 0.0
                )
                novelty = 1.0
                if selected:
                    novelty = 1.0 - max(
                        self._jaccard_similarity(
                            candidate_tokens,
                            self._tokenize_text(chosen.page_content),
                        )
                        for chosen in selected
                    )

                source_key = str(candidate.metadata.get("file_hash") or candidate.metadata.get("source") or "unknown")
                page_key = (source_key, candidate.metadata.get("page"))
                retrieval_topic = self._normalize_text(candidate.metadata.get("retrieval_topic", ""))
                topic_bonus = 0.35 if retrieval_topic and retrieval_topic in normalized_requested_topics else 0.0
                source_bonus = 0.15 if source_key not in selected_sources else 0.0
                page_bonus = 0.1 if page_key not in selected_pages else 0.0
                raw_rank = int(candidate.metadata.get("_raw_rank", 9999))
                relevance_bonus = 1.0 / (1.0 + raw_rank)

                score = (
                    (coverage_overlap * 1.45)
                    + (topic_overlap * 1.15)
                    + (novelty * 1.2)
                    + topic_bonus
                    + source_bonus
                    + page_bonus
                    + (relevance_bonus * 0.25)
                )
                if score > best_score:
                    best_score = score
                    best_doc = candidate

            if best_doc is None:
                break

            remaining.remove(best_doc)
            selected.append(best_doc)
            source_key = str(best_doc.metadata.get("file_hash") or best_doc.metadata.get("source") or "unknown")
            selected_sources.add(source_key)
            selected_pages.add((source_key, best_doc.metadata.get("page")))

        return selected

    @staticmethod
    def _match_option_text(candidate: Any, option_values: List[str]) -> Optional[int]:
        normalized_candidate = QuizGenerator._normalize_text(candidate)
        for index, option in enumerate(option_values):
            if QuizGenerator._normalize_text(option) == normalized_candidate:
                return index
        return None

    def _normalize_option_values(self, options: Any) -> Optional[List[str]]:
        if isinstance(options, dict):
            if len(options) != 4:
                return None
            if all(letter in options for letter in ("A", "B", "C", "D")):
                raw_values = [options[letter] for letter in ("A", "B", "C", "D")]
            else:
                raw_values = list(options.values())
        elif isinstance(options, list):
            if len(options) != 4:
                return None
            raw_values = options
        else:
            return None

        normalized_values: List[str] = []
        seen = set()
        for value in raw_values:
            text = re.sub(r"\s+", " ", str(value or "").strip())
            if not text:
                return None
            normalized = self._normalize_text(text)
            if normalized in seen:
                return None
            seen.add(normalized)
            normalized_values.append(text)

        return normalized_values

    def _resolve_correct_index(self, question: Dict[str, Any], option_values: List[str]) -> Optional[int]:
        raw_index = question.get("correct_index")
        if raw_index is not None:
            try:
                index_value = int(raw_index)
                if 0 <= index_value < len(option_values):
                    return index_value
                if 1 <= index_value <= len(option_values):
                    return index_value - 1
            except (TypeError, ValueError):
                pass

        raw_answer = question.get("correct_answer")
        if isinstance(raw_answer, str):
            answer_text = raw_answer.strip()
            if answer_text.upper() in ("A", "B", "C", "D"):
                letter_index = ord(answer_text.upper()) - ord("A")
                if 0 <= letter_index < len(option_values):
                    return letter_index
            matched_index = self._match_option_text(answer_text, option_values)
            if matched_index is not None:
                return matched_index

        raw_option_text = question.get("correct_option_text")
        matched_index = self._match_option_text(raw_option_text, option_values)
        if matched_index is not None:
            return matched_index

        return None

    def _stable_shuffle_options(
        self,
        question_text: str,
        option_values: List[str],
        correct_index: int,
    ) -> Tuple[Dict[str, str], str]:
        letters = ["A", "B", "C", "D"]
        order = list(range(len(option_values)))
        seed_source = f"{question_text}||{'||'.join(option_values)}"
        seed = int(hashlib.sha256(seed_source.encode("utf-8")).hexdigest()[:16], 16)
        rng = random.Random(seed)
        rng.shuffle(order)

        shuffled_options = {
            letters[new_index]: option_values[original_index]
            for new_index, original_index in enumerate(order)
        }
        remapped_correct = letters[order.index(correct_index)]
        return shuffled_options, remapped_correct

    def _question_signature(self, question_text: str) -> str:
        return self._normalize_text(question_text)

    def _option_signature(self, option_values: List[str]) -> Tuple[str, ...]:
        return tuple(self._normalize_text(option) for option in option_values)

    def _coerce_slot_id(
        self,
        raw_item: Dict[str, Any],
        requested_slots: Dict[str, Dict[str, Any]],
        fallback_slot_ids: List[str],
        used_slot_ids: set[str],
    ) -> Optional[str]:
        raw_slot_id = str(raw_item.get("slot_id") or "").strip()
        if raw_slot_id in requested_slots and raw_slot_id not in used_slot_ids:
            return raw_slot_id
        while fallback_slot_ids:
            fallback_slot_id = fallback_slot_ids.pop(0)
            if fallback_slot_id not in used_slot_ids:
                return fallback_slot_id
        return None

    def _normalize_generated_batch(
        self,
        raw_items: List[Dict[str, Any]],
        batch_slots: List[Dict[str, Any]],
        question_signatures: set[str],
        option_signatures: set[Tuple[str, ...]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], int, Dict[str, int]]:
        requested_slots = {slot["slot_id"]: slot for slot in batch_slots}
        ordered_slot_ids = [slot["slot_id"] for slot in batch_slots]
        used_slot_ids: set[str] = set()
        formatted_questions: List[Dict[str, Any]] = []
        malformed_count = 0
        rejection_reasons: Counter = Counter()
        generated_count_before_validation = len(raw_items)
        length_bias_warning_count = 0

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                malformed_count += 1
                rejection_reasons["non_dict_item"] += 1
                continue

            slot_id = self._coerce_slot_id(
                raw_item=raw_item,
                requested_slots=requested_slots,
                fallback_slot_ids=ordered_slot_ids,
                used_slot_ids=used_slot_ids,
            )
            if not slot_id:
                malformed_count += 1
                rejection_reasons["no_slot_id"] += 1
                continue

            question_text = str(raw_item.get("question") or "").strip()
            option_values = self._normalize_option_values(raw_item.get("options"))
            if not question_text or not option_values:
                malformed_count += 1
                rejection_reasons["bad_question_or_options"] += 1
                continue

            correct_index = self._resolve_correct_index(raw_item, option_values)
            if correct_index is None:
                malformed_count += 1
                rejection_reasons["unresolvable_correct_answer"] += 1
                continue

            # P0: structural MCQ validation. Reject (do not auto-fix) so the
            # slot rolls into missing_slots and the supplement pass refills.
            structural_ok, structural_reason = validate_mcq_structure(
                question_text, option_values, correct_index
            )
            if not structural_ok:
                malformed_count += 1
                rejection_reasons[structural_reason] += 1
                logger.info(
                    "MCQ rejected slot=%s reason=%s question=%r",
                    slot_id,
                    structural_reason,
                    question_text[:120],
                )
                continue

            # Soft check (warning only, no reject): correct option much longer
            # than every distractor. Many legitimate detailed answers trip this.
            if _is_correct_length_outlier(option_values, correct_index):
                length_bias_warning_count += 1
                logger.warning(
                    "MCQ length-bias warning slot=%s correct_len=%s longest_distractor_len=%s",
                    slot_id,
                    len(option_values[correct_index]),
                    max(len(o) for i, o in enumerate(option_values) if i != correct_index),
                )

            question_signature = self._question_signature(question_text)
            option_signature = self._option_signature(option_values)
            if question_signature in question_signatures:
                malformed_count += 1
                rejection_reasons["duplicate_question"] += 1
                continue

            options_dict, correct_answer = self._stable_shuffle_options(
                question_text=question_text,
                option_values=option_values,
                correct_index=correct_index,
            )

            slot = requested_slots[slot_id]
            formatted_questions.append({
                "slot_id": slot_id,
                "topic_group": slot.get("topic_group"),
                "topic_group_label": slot.get("topic_group_label"),
                "coverage_item": slot.get("coverage_item"),
                "support_level": slot.get("support_level"),
                "question_form": slot.get("question_form"),
                "trap_type": slot.get("trap_type"),
                "question": question_text,
                "options": options_dict,
                "correct_answer": correct_answer,
            })
            question_signatures.add(question_signature)
            option_signatures.add(option_signature)
            used_slot_ids.add(slot_id)

        missing_slots = [
            slot
            for slot in batch_slots
            if slot["slot_id"] not in used_slot_ids
        ]

        # Counters requested by P0.5 telemetry.
        structural_reasons = {
            "all_of_above", "none_of_above", "combined_answer",
            "suspicious_meta_option", "semantic_duplicate_option",
            "invalid_mcq_structure",
        }
        rejected_by_structure_count = sum(
            count for reason, count in rejection_reasons.items()
            if reason in structural_reasons
        )
        quiz_logger.info(
            "MCQ batch telemetry: generated_before_validation=%s "
            "accepted_after_validation=%s rejected_by_structure=%s "
            "length_bias_warnings=%s reasons=%s",
            generated_count_before_validation,
            len(formatted_questions),
            rejected_by_structure_count,
            length_bias_warning_count,
            dict(rejection_reasons),
        )
        return formatted_questions, missing_slots, malformed_count, dict(rejection_reasons)

    def _invoke_generation_pass(
        self,
        *,
        context_documents: List[Document],
        topic: str,
        difficulty: str,
        language: str,
        total_target: int,
        batch_slots: List[Dict[str, Any]],
        existing_questions: List[Dict[str, Any]],
        generation_mode: str,
        cost_protected: bool = False,
        call_index: Optional[int] = None,
        planned_calls: Optional[int] = None,
        llm_provider_override: Optional["BaseLLM"] = None,
        rejection_hint: Optional[str] = None,
        key_pool: Optional[Any] = None,
        current_key_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], int]:
        prompt = self.prompt_vi if language == "vi" else self.prompt_en
        context = self._format_context_documents(context_documents)
        existing_limit, existing_chars = self._existing_question_prompt_budget(
            generation_mode=generation_mode,
            cost_protected=cost_protected,
        )
        existing_questions_text = self._format_existing_questions_for_prompt(
            existing_questions,
            max_items=existing_limit,
            max_chars=existing_chars,
        )
        slot_section = self._format_slot_section(batch_slots)
        if rejection_hint:
            # Inject rejection feedback at the top of the slot section so the
            # model sees the structural failures from the previous pass before
            # writing replacements. Kept short to avoid blowing the prompt.
            slot_section = f"{rejection_hint}\n\n{slot_section}"
        batch_target = len(batch_slots)
        max_tokens = self._max_tokens_for_generation_pass(
            batch_target=batch_target,
            generation_mode=generation_mode,
            cost_protected=cost_protected,
        )

        # Retry-on-other-key loop. Each iteration uses one provider bound to
        # one Groq key; on 429 we mark the key, rotate to a fresh one, and
        # re-issue chain.invoke. Bounded by max_attempts. Non-429 errors
        # propagate unchanged.
        active_provider = llm_provider_override or self._llm_provider
        active_key_info = current_key_info
        pool_size = key_pool.size if key_pool is not None else 0
        max_attempts = max(1, min(3, pool_size)) if key_pool is not None else 1

        logger.info(
            "Quiz generation pass: mode=%s call=%s/%s slots=%s context_docs=%s context_chars=%s existing_questions=%s existing_chars=%s max_tokens=%s",
            generation_mode,
            call_index if call_index is not None else "-",
            planned_calls if planned_calls is not None else "-",
            batch_target,
            len(context_documents),
            len(context),
            len(existing_questions),
            len(existing_questions_text),
            max_tokens,
        )

        policy = DIFFICULTY_POLICIES.get(difficulty, DIFFICULTY_POLICIES["medium"])
        attempt = 0
        response = None
        while True:
            attempt += 1
            llm_json = active_provider.get_llm(json_mode=True, max_tokens=max_tokens)
            chain = prompt | llm_json
            _purpose = generation_mode
            _key_id = getattr(active_provider, "key_id", None) or "-"
            _masked_key = getattr(active_provider, "masked_key", None) or "-"

            logger.info(
                "LLM_REQUEST_START purpose=%s key_id=%s masked_key=%s max_tokens=%s attempt=%d/%d",
                _purpose, _key_id, _masked_key, max_tokens, attempt, max_attempts,
            )
            _t0 = time.monotonic()
            try:
                response = chain.invoke({
                    "context": context,
                    "topic": topic,
                    "difficulty": difficulty,
                    "difficulty_policy": policy["generation_instruction"],
                    "total_target": total_target,
                    "batch_target": batch_target,
                    "slot_section": slot_section,
                    "existing_questions": existing_questions_text,
                    "generation_mode": generation_mode,
                })
            except Exception as _invoke_err:
                _dur_ms = int((time.monotonic() - _t0) * 1000)
                _err_str = str(_invoke_err).lower()
                _is_429 = (
                    "429" in _err_str
                    or "rate limit" in _err_str
                    or "rate_limit" in _err_str
                    or "too many requests" in _err_str
                )
                if _is_429:
                    logger.warning(
                        "LLM_REQUEST_429 purpose=%s key_id=%s masked_key=%s duration_ms=%d attempt=%d/%d error=%s",
                        _purpose, _key_id, _masked_key, _dur_ms, attempt, max_attempts, _invoke_err,
                    )
                else:
                    logger.error(
                        "LLM_REQUEST_ERROR purpose=%s key_id=%s masked_key=%s duration_ms=%d attempt=%d/%d error=%s",
                        _purpose, _key_id, _masked_key, _dur_ms, attempt, max_attempts, _invoke_err,
                    )

                # Only attempt key-switching on 429 with a usable KeyPool.
                if not _is_429 or key_pool is None or active_key_info is None:
                    # Mark error on the active key so flush_to_db sees it;
                    # do not switch.
                    if key_pool is not None and active_key_info is not None:
                        try:
                            key_pool.mark_error(active_key_info["id"])
                        except Exception:
                            pass
                    raise

                # 429 path: mark current key as errored, then try to swap.
                try:
                    key_pool.mark_error(active_key_info["id"])
                except Exception:
                    pass
                if attempt >= max_attempts:
                    logger.error(
                        "ALL_KEYS_EXHAUSTED purpose=%s attempts=%d/%d last_key_id=%s",
                        _purpose, attempt, max_attempts, _key_id,
                    )
                    raise
                next_info = key_pool.next_key()
                if next_info is None:
                    logger.error(
                        "ALL_KEYS_EXHAUSTED purpose=%s attempts=%d/%d reason=no_more_keys",
                        _purpose, attempt, max_attempts,
                    )
                    raise
                logger.warning(
                    "KEY_SWITCH reason=429 purpose=%s from_key_id=%s to_key_id=%s to_masked=%s attempt=%d/%d",
                    _purpose,
                    _key_id,
                    str(next_info["id"]),
                    next_info.get("masked_key", "?"),
                    attempt,
                    max_attempts,
                )
                active_key_info = next_info
                active_provider = LLMFactory.create(
                    groq_api_key=next_info["plain_key"],
                    key_id=str(next_info["id"]),
                    masked_key=next_info.get("masked_key"),
                )
                continue

            # Success path
            logger.info(
                "LLM_REQUEST_SUCCESS purpose=%s key_id=%s masked_key=%s duration_ms=%d attempt=%d/%d",
                _purpose, _key_id, _masked_key, int((time.monotonic() - _t0) * 1000),
                attempt, max_attempts,
            )
            if key_pool is not None and active_key_info is not None:
                try:
                    key_pool.mark_success(active_key_info["id"])
                except Exception:
                    pass
            break

        content = response.content if hasattr(response, "content") else str(response)
        quiz_data = self._parse_quiz_response(content)
        if not quiz_data:
            quiz_data = self._salvage_partial_json(content)
        raw_items = quiz_data.get("quiz", []) if quiz_data else []
        malformed_from_parse = 0 if quiz_data else batch_target
        return raw_items, malformed_from_parse

    @staticmethod
    def _build_rejection_hint(
        rejection_reasons: Dict[str, int],
        language: str,
    ) -> Optional[str]:
        """Translate per-batch rejection reasons into a short prompt nudge.

        Used to feed structural-failure feedback into the next generation pass
        so the model can avoid repeating the same defect on refill slots.
        Returns None if there is nothing actionable to say.
        """
        if not rejection_reasons:
            return None
        reason_to_text_en = {
            "all_of_above": (
                "previous answers used 'all of the above' style aggregator options"
            ),
            "none_of_above": (
                "previous answers used 'none of the above' style aggregator options"
            ),
            "combined_answer": (
                "previous answers used combined options like 'A and B' / 'cả A và B' "
                "that merge other choices"
            ),
            "suspicious_meta_option": (
                "previous answers used meta phrases that reference other options"
            ),
            "semantic_duplicate_option": (
                "previous answers contained two options with near-identical meaning"
            ),
        }
        reason_to_text_vi = {
            "all_of_above": (
                "lần trước có đáp án dạng 'tất cả các đáp án trên' / 'all of the above'"
            ),
            "none_of_above": (
                "lần trước có đáp án dạng 'không có đáp án nào đúng' / 'none of the above'"
            ),
            "combined_answer": (
                "lần trước có đáp án dạng 'A và B' / 'cả A và C' gom các lựa chọn khác"
            ),
            "suspicious_meta_option": (
                "lần trước có đáp án meta nhắc đến các lựa chọn khác"
            ),
            "semantic_duplicate_option": (
                "lần trước có hai đáp án gần như giống nhau về nghĩa"
            ),
        }
        translator = reason_to_text_vi if language == "vi" else reason_to_text_en
        actionable: List[str] = []
        for reason, count in rejection_reasons.items():
            text = translator.get(reason)
            if text:
                actionable.append(f"- {text} ({count}x)")
        if not actionable:
            return None
        if language == "vi":
            header = (
                "REFILL FEEDBACK — các câu lần trước bị loại do lỗi cấu trúc đáp án:"
            )
            footer = (
                "Hãy tạo các câu thay thế với ĐÚNG MỘT đáp án đúng độc lập, "
                "không có đáp án meta, không gom các lựa chọn khác."
            )
        else:
            header = (
                "REFILL FEEDBACK — previous questions were rejected for structural defects:"
            )
            footer = (
                "Generate replacement questions with EXACTLY ONE independent correct option, "
                "no meta-answer choices, and no combined-answer patterns."
            )
        return f"{header}\n" + "\n".join(actionable) + f"\n{footer}"

    def _run_batch_generation(
        self,
        *,
        raw_documents: List[Document],
        batch_slots: List[Dict[str, Any]],
        topic: str,
        difficulty: str,
        language: str,
        total_target: int,
        existing_questions: List[Dict[str, Any]],
        question_signatures: set[str],
        option_signatures: set[Tuple[str, ...]],
        enable_retry: bool = True,
        cost_protected: bool = False,
        call_index_start: int = 1,
        planned_calls: Optional[int] = None,
        llm_provider_override: Optional["BaseLLM"] = None,
        key_pool: Optional[Any] = None,
        current_key_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
        batch_results: List[Dict[str, Any]] = []
        malformed_count = 0
        retry_count = 0
        call_count = 0
        estimated_completion_tokens = 0

        context_documents = self._select_batch_context_documents(
            raw_documents,
            batch_slots,
            budget_override=self._context_window_for_mode(
                len(batch_slots),
                generation_mode="primary_batch",
                cost_protected=cost_protected,
            ),
        )
        raw_items, parse_failures = self._invoke_generation_pass(
            context_documents=context_documents,
            topic=topic,
            difficulty=difficulty,
            language=language,
            total_target=total_target,
            batch_slots=batch_slots,
            existing_questions=existing_questions,
            generation_mode="primary_batch",
            cost_protected=cost_protected,
            call_index=call_index_start,
            planned_calls=planned_calls,
            llm_provider_override=llm_provider_override,
            key_pool=key_pool,
            current_key_info=current_key_info,
        )
        call_count += 1
        estimated_completion_tokens += self._max_tokens_for_generation_pass(
            len(batch_slots),
            "primary_batch",
            cost_protected,
        )
        malformed_count += parse_failures
        accepted_items, missing_slots, normalized_failures, primary_rejections = (
            self._normalize_generated_batch(
                raw_items=raw_items,
                batch_slots=batch_slots,
                question_signatures=question_signatures,
                option_signatures=option_signatures,
            )
        )
        malformed_count += normalized_failures
        batch_results.extend(accepted_items)
        aggregated_rejections: Counter = Counter(primary_rejections)

        if enable_retry and missing_slots:
            retry_count += 1
            retry_context_documents = self._select_batch_context_documents(
                raw_documents,
                missing_slots,
                budget_override=self._context_window_for_mode(
                    len(missing_slots),
                    generation_mode="batch_retry_count_first",
                    cost_protected=cost_protected,
                ),
            )
            retry_hint = self._build_rejection_hint(primary_rejections, language)
            raw_items, parse_failures = self._invoke_generation_pass(
                context_documents=retry_context_documents,
                topic=topic,
                difficulty=difficulty,
                language=language,
                total_target=total_target,
                batch_slots=missing_slots,
                existing_questions=existing_questions + batch_results,
                generation_mode="batch_retry_count_first",
                cost_protected=cost_protected,
                call_index=call_index_start + call_count,
                planned_calls=planned_calls,
                llm_provider_override=llm_provider_override,
                rejection_hint=retry_hint,
                key_pool=key_pool,
                current_key_info=current_key_info,
            )
            call_count += 1
            estimated_completion_tokens += self._max_tokens_for_generation_pass(
                len(missing_slots),
                "batch_retry_count_first",
                cost_protected,
            )
            malformed_count += parse_failures
            accepted_retry, missing_slots, normalized_failures, retry_rejections = (
                self._normalize_generated_batch(
                    raw_items=raw_items,
                    batch_slots=missing_slots,
                    question_signatures=question_signatures,
                    option_signatures=option_signatures,
                )
            )
            malformed_count += normalized_failures
            batch_results.extend(accepted_retry)
            aggregated_rejections.update(retry_rejections)

        return batch_results, missing_slots, {
            "malformed_count": malformed_count,
            "retry_count": retry_count,
            "refill_attempt_count": retry_count,
            "call_count": call_count,
            "estimated_completion_tokens": estimated_completion_tokens,
            "rejection_reasons": dict(aggregated_rejections),
        }

    def _run_targeted_refill(
        self,
        *,
        raw_documents: List[Document],
        missing_slots: List[Dict[str, Any]],
        topic: str,
        difficulty: str,
        language: str,
        total_target: int,
        existing_questions: List[Dict[str, Any]],
        question_signatures: set[str],
        option_signatures: set[Tuple[str, ...]],
        generation_mode: str = "global_refill_1",
        support_level_override: Optional[str] = None,
        cost_protected: bool = False,
        call_index: int = 1,
        planned_calls: Optional[int] = None,
        llm_provider_override: Optional["BaseLLM"] = None,
        rejection_hint: Optional[str] = None,
        key_pool: Optional[Any] = None,
        current_key_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
        if not missing_slots:
            return [], [], {
                "malformed_count": 0,
                "retry_count": 0,
                "call_count": 0,
                "estimated_completion_tokens": 0,
            }

        refill_slots = []
        for slot in missing_slots:
            refill_slot = dict(slot)
            if support_level_override:
                refill_slot["support_level"] = support_level_override
            refill_slots.append(refill_slot)

        refill_context = self._select_batch_context_documents(
            raw_documents,
            refill_slots,
            budget_override=self._context_window_for_mode(
                len(refill_slots),
                generation_mode=generation_mode,
                cost_protected=cost_protected,
            ),
        )
        raw_items, parse_failures = self._invoke_generation_pass(
            context_documents=refill_context,
            topic=topic,
            difficulty=difficulty,
            language=language,
            total_target=total_target,
            batch_slots=refill_slots,
            existing_questions=existing_questions,
            generation_mode=generation_mode,
            cost_protected=cost_protected,
            call_index=call_index,
            planned_calls=planned_calls,
            llm_provider_override=llm_provider_override,
            rejection_hint=rejection_hint,
            key_pool=key_pool,
            current_key_info=current_key_info,
        )
        accepted_items, still_missing, normalized_failures, refill_rejections = (
            self._normalize_generated_batch(
                raw_items=raw_items,
                batch_slots=refill_slots,
                question_signatures=question_signatures,
                option_signatures=option_signatures,
            )
        )
        return accepted_items, still_missing, {
            "malformed_count": parse_failures + normalized_failures,
            "retry_count": 1,
            "refill_attempt_count": 1,
            "call_count": 1,
            "estimated_completion_tokens": self._max_tokens_for_generation_pass(
                len(refill_slots),
                generation_mode,
                cost_protected,
            ),
            "rejection_reasons": refill_rejections,
        }

    def _execute_exact_count_plan(
        self,
        *,
        raw_documents: List[Document],
        blueprint: Dict[str, Any],
        topic: str,
        difficulty: str,
        language: str,
        num_questions: int,
        cost_protected: bool = False,
        blueprint_attempted: bool = False,
        key_pool: Optional[Any] = None,
    ) -> Dict[str, Any]:
        slots = blueprint.get("slots", [])[:num_questions]

        # --- Topic-group-aligned batching ---
        batch_plan = self._plan_topic_group_batches(slots)

        question_signatures: set[str] = set()
        option_signatures: set[Tuple[str, ...]] = set()
        all_questions: List[Dict[str, Any]] = []
        missing_slots: List[Dict[str, Any]] = []
        total_malformed = 0
        total_retries = 0
        total_generation_calls = 0
        estimated_completion_used = 0
        refill_count = 0
        remaining_slots_after_refill_1 = 0
        remaining_slots_after_refill_2 = 0
        budget_cap_hit = False
        aggregated_rejection_reasons: Counter = Counter()
        planned_generation_calls = len(batch_plan) + (2 if cost_protected else 1)
        max_generation_calls = self._max_generation_calls(num_questions)
        max_completion_budget = self._max_est_completion_tokens(num_questions)

        for batch_index, batch_slots in enumerate(batch_plan, start=1):
            if not batch_slots:
                continue

            # --- Key rotation: pick next key from pool for this batch ---
            batch_llm_override: Optional[BaseLLM] = None
            _current_key_info = None
            if key_pool is not None:
                _current_key_info = key_pool.next_key()
                if _current_key_info is not None:
                    batch_llm_override = LLMFactory.create(
                        groq_api_key=_current_key_info["plain_key"],
                        key_id=str(_current_key_info["id"]),
                        masked_key=_current_key_info.get("masked_key"),
                    )

            try:
                batch_questions, batch_missing, batch_stats = self._run_batch_generation(
                    raw_documents=raw_documents,
                    batch_slots=batch_slots,
                    topic=topic,
                    difficulty=difficulty,
                    language=language,
                    total_target=num_questions,
                    existing_questions=all_questions,
                    question_signatures=question_signatures,
                    option_signatures=option_signatures,
                    enable_retry=not cost_protected,
                    cost_protected=cost_protected,
                    call_index_start=total_generation_calls + 1,
                    planned_calls=planned_generation_calls,
                    llm_provider_override=batch_llm_override,
                    key_pool=key_pool,
                    current_key_info=_current_key_info,
                )
            except Exception:
                # Inner pass already handled mark_error/key swap on 429.
                raise
            total_malformed += batch_stats["malformed_count"]
            total_retries += batch_stats["retry_count"]
            total_generation_calls += batch_stats["call_count"]
            estimated_completion_used += batch_stats["estimated_completion_tokens"]
            aggregated_rejection_reasons.update(batch_stats.get("rejection_reasons", {}))
            all_questions.extend(batch_questions)
            missing_slots.extend(batch_missing)
            logger.info(
                "Quiz batch %s/%s: requested=%s generated=%s missing=%s context_budget=%s",
                batch_index,
                len(batch_plan),
                len(batch_slots),
                len(batch_questions),
                len(batch_missing),
                self._context_window_for_mode(
                    len(batch_slots),
                    generation_mode="primary_batch",
                    cost_protected=cost_protected,
                ),
            )

        remaining_slots = missing_slots[:]

        if remaining_slots:
            if max_generation_calls is None or total_generation_calls < max_generation_calls:
                refill_llm_override: Optional[BaseLLM] = None
                _refill_key = None
                if key_pool is not None:
                    _refill_key = key_pool.next_key()
                    if _refill_key is not None:
                        refill_llm_override = LLMFactory.create(
                            groq_api_key=_refill_key["plain_key"],
                            key_id=str(_refill_key["id"]),
                            masked_key=_refill_key.get("masked_key"),
                        )
                try:
                    refill_questions, remaining_slots, refill_stats = self._run_targeted_refill(
                        raw_documents=raw_documents,
                        missing_slots=remaining_slots,
                        topic=topic,
                        difficulty=difficulty,
                        language=language,
                        total_target=num_questions,
                        existing_questions=all_questions,
                        question_signatures=question_signatures,
                        option_signatures=option_signatures,
                        generation_mode="global_refill_1",
                        support_level_override=None,
                        cost_protected=cost_protected,
                        call_index=total_generation_calls + 1,
                        planned_calls=planned_generation_calls,
                        llm_provider_override=refill_llm_override,
                        rejection_hint=self._build_rejection_hint(
                            dict(aggregated_rejection_reasons), language
                        ),
                        key_pool=key_pool,
                        current_key_info=_refill_key,
                    )
                except Exception:
                    # Inner pass already handled mark_error/key swap on 429.
                    raise
                all_questions.extend(refill_questions)
                total_malformed += refill_stats["malformed_count"]
                total_retries += refill_stats["retry_count"]
                total_generation_calls += refill_stats["call_count"]
                estimated_completion_used += refill_stats["estimated_completion_tokens"]
                aggregated_rejection_reasons.update(refill_stats.get("rejection_reasons", {}))
                refill_count += 1
                remaining_slots_after_refill_1 = len(remaining_slots)
            else:
                budget_cap_hit = True
                remaining_slots_after_refill_1 = len(remaining_slots)
        else:
            remaining_slots_after_refill_1 = 0

        if cost_protected and remaining_slots:
            can_run_second_refill = (
                self._should_run_second_refill(num_questions, len(remaining_slots))
                and (max_generation_calls is None or total_generation_calls < max_generation_calls)
            )
            projected_second_refill = self._max_tokens_for_generation_pass(
                len(remaining_slots),
                "global_refill_2",
                cost_protected=True,
            )
            if (
                can_run_second_refill
                and max_completion_budget is not None
                and estimated_completion_used + projected_second_refill > max_completion_budget
            ):
                can_run_second_refill = False
                budget_cap_hit = True

            if can_run_second_refill:
                refill2_llm_override: Optional[BaseLLM] = None
                _refill2_key = None
                if key_pool is not None:
                    _refill2_key = key_pool.next_key()
                    if _refill2_key is not None:
                        refill2_llm_override = LLMFactory.create(
                            groq_api_key=_refill2_key["plain_key"],
                            key_id=str(_refill2_key["id"]),
                            masked_key=_refill2_key.get("masked_key"),
                        )
                try:
                    refill_questions, remaining_slots, refill_stats = self._run_targeted_refill(
                        raw_documents=raw_documents,
                        missing_slots=remaining_slots,
                        topic=topic,
                        difficulty=difficulty,
                        language=language,
                        total_target=num_questions,
                        existing_questions=all_questions,
                        question_signatures=question_signatures,
                        option_signatures=option_signatures,
                        generation_mode="global_refill_2",
                        support_level_override="adjacent_in_scope",
                        cost_protected=True,
                        call_index=total_generation_calls + 1,
                        planned_calls=planned_generation_calls,
                        llm_provider_override=refill2_llm_override,
                        rejection_hint=self._build_rejection_hint(
                            dict(aggregated_rejection_reasons), language
                        ),
                        key_pool=key_pool,
                        current_key_info=_refill2_key,
                    )
                except Exception:
                    # Inner pass already handled mark_error/key swap on 429.
                    raise
                all_questions.extend(refill_questions)
                total_malformed += refill_stats["malformed_count"]
                total_retries += refill_stats["retry_count"]
                total_generation_calls += refill_stats["call_count"]
                estimated_completion_used += refill_stats["estimated_completion_tokens"]
                aggregated_rejection_reasons.update(refill_stats.get("rejection_reasons", {}))
                refill_count += 1
            elif remaining_slots:
                budget_cap_hit = True

            remaining_slots_after_refill_2 = len(remaining_slots)
        else:
            remaining_slots_after_refill_2 = len(remaining_slots)

        slot_order = {slot["slot_id"]: index for index, slot in enumerate(slots)}
        ordered_questions = sorted(
            all_questions,
            key=lambda item: slot_order.get(item.get("slot_id", ""), 10_000),
        )
        for index, question in enumerate(ordered_questions, start=1):
            question["question_number"] = index
            question.pop("slot_id", None)
            question.pop("topic_group", None)
            question.pop("topic_group_label", None)
            question.pop("coverage_item", None)
            question.pop("support_level", None)
            question.pop("question_form", None)
            question.pop("trap_type", None)

        group_labels = [group.get("label", group.get("group_id", "group")) for group in blueprint.get("topic_groups", [])]
        structural_reason_keys = {
            "all_of_above", "none_of_above", "combined_answer",
            "suspicious_meta_option", "semantic_duplicate_option",
            "invalid_mcq_structure",
        }
        rejected_by_structure_total = sum(
            count for reason, count in aggregated_rejection_reasons.items()
            if reason in structural_reason_keys
        )
        logger.info(
            "Quiz exact-count plan: requested=%s planned_slots=%s topic_groups=%s raw_pool=%s "
            "malformed=%s retries=%s refill_attempt_count=%s "
            "rejected_by_structure=%s rejection_reasons=%s "
            "planned_calls=%s actual_calls=%s refill_count=%s "
            "remaining_slots_after_refill_1=%s remaining_slots_after_refill_2=%s "
            "budget_cap_hit=%s remaining_slots=%s",
            num_questions,
            len(slots),
            group_labels,
            len(raw_documents),
            total_malformed,
            total_retries,
            refill_count,
            rejected_by_structure_total,
            dict(aggregated_rejection_reasons),
            planned_generation_calls + (1 if blueprint_attempted else 0),
            total_generation_calls + (1 if blueprint_attempted else 0),
            refill_count,
            remaining_slots_after_refill_1,
            remaining_slots_after_refill_2,
            budget_cap_hit,
            len(remaining_slots),
        )

        return {
            "questions": ordered_questions,
            "remaining_slots": remaining_slots,
            "stats": {
                "malformed_count": total_malformed,
                "retry_count": total_retries,
                "refill_attempt_count": refill_count,
                "planned_calls": planned_generation_calls + (1 if blueprint_attempted else 0),
                "actual_calls": total_generation_calls + (1 if blueprint_attempted else 0),
                "refill_count": refill_count,
                "remaining_slots_after_refill_1": remaining_slots_after_refill_1,
                "remaining_slots_after_refill_2": remaining_slots_after_refill_2,
                "budget_cap_hit": budget_cap_hit,
                "estimated_completion_used": estimated_completion_used,
                "rejection_reasons": dict(aggregated_rejection_reasons),
                "rejected_by_structure_count": rejected_by_structure_total,
            },
        }

    def _generate_quiz_core_vnext(
        self,
        *,
        topic: str,
        num_questions: int,
        difficulty: str,
        language: str,
        raw_documents: List[Document],
        topics: Optional[List[str]] = None,
        raw_document_count: int = 0,
    ) -> Dict[str, Any]:
        """Exact-count quiz generation using slot planning, batched generation, and targeted refill."""
        raw_documents = self._dedupe_documents(raw_documents)
        if not raw_documents:
            return {
                "success": False,
                "partial": False,
                "questions": [],
                "message": "Context rong, khong the tao quiz",
                "sources": [],
                "num_questions_requested": num_questions,
                "num_questions_generated": 0,
            }

        sources = self._extract_document_citations(raw_documents)
        topics = topics or [topic]
        raw_document_count = raw_document_count or len(raw_documents)
        cost_protected = self._is_large_request(num_questions)
        blueprint_context_budget = min(len(raw_documents), max(12, min(24, num_questions if num_questions < 24 else 24)))
        should_use_blueprint = self._should_use_blueprint(
            num_questions=num_questions,
            topics=topics,
            raw_document_count=raw_document_count,
            final_budget=blueprint_context_budget,
        )
        blueprint_attempted = False
        blueprint_skip_reason: Optional[str] = None

        try:
            if should_use_blueprint:
                blueprint_attempted = True
                blueprint_context_documents = self._select_context_documents(
                    documents=raw_documents,
                    topics=topics,
                    final_budget=blueprint_context_budget,
                )
                blueprint_context = self._format_context_documents(blueprint_context_documents)
                blueprint, blueprint_failure_reason = self._build_blueprint_chunked(
                    context=blueprint_context,
                    topic=topic,
                    difficulty=difficulty,
                    language=language,
                    num_questions=num_questions,
                    topics=topics,
                )
                if blueprint_failure_reason == "length_limit":
                    blueprint_skip_reason = "blueprint skipped due to length limit"
                    logger.warning("Blueprint skipped due to length limit; falling back to local slot planner")
                elif blueprint_failure_reason:
                    blueprint_skip_reason = "blueprint skipped due to parse/generation fallback"
                    logger.warning(
                        "Blueprint skipped due to %s; falling back to local slot planner",
                        blueprint_failure_reason,
                    )
            else:
                if self._should_skip_blueprint_for_request(num_questions, topics):
                    blueprint_skip_reason = "blueprint skipped due to large request"
                    logger.info("Blueprint skipped due to large request")
                blueprint = self._normalize_blueprint(
                    blueprint={},
                    topic=topic,
                    num_questions=num_questions,
                    difficulty=difficulty,
                )

            logger.info(
                "Quiz planning: requested=%s raw_pool=%s blueprint=%s blueprint_context_budget=%s cost_protected=%s skip_reason=%s",
                num_questions,
                len(raw_documents),
                blueprint_attempted,
                blueprint_context_budget if blueprint_attempted else 0,
                cost_protected,
                blueprint_skip_reason or "",
            )
            plan_result = self._execute_exact_count_plan(
                raw_documents=raw_documents,
                blueprint=blueprint,
                topic=topic,
                difficulty=difficulty,
                language=language,
                num_questions=num_questions,
                cost_protected=cost_protected,
                blueprint_attempted=blueprint_attempted,
                key_pool=self._key_pool,
            )
            formatted_quiz = plan_result["questions"][:num_questions]
            remaining_slots = plan_result["remaining_slots"]
            final_count = len(formatted_quiz)
            exact_count_reached = final_count == num_questions
            partial_success = self._is_partial_success(num_questions, final_count)
            plan_stats = plan_result.get("stats", {})

            if formatted_quiz:
                logger.info("Sample question 1: %s", formatted_quiz[0])

            if not exact_count_reached:
                message = self._build_user_facing_shortfall_message(
                    num_questions=num_questions,
                    final_count=final_count,
                    blueprint_skip_reason=blueprint_skip_reason,
                    plan_stats=plan_stats,
                    remaining_slots=remaining_slots,
                )
                return {
                    "success": partial_success,
                    "partial": partial_success,
                    "questions": formatted_quiz,
                    "message": message,
                    "sources": sources,
                    "num_questions_requested": num_questions,
                    "num_questions_generated": final_count,
                    "error": None if partial_success else message,
                    "remaining_slots": [slot["slot_id"] for slot in remaining_slots],
                }

            return {
                "success": True,
                "partial": False,
                "questions": formatted_quiz,
                "message": "",
                "sources": sources,
                "num_questions_requested": num_questions,
                "num_questions_generated": final_count,
            }

        except Exception as exc:
            logger.error("Error generating quiz: %s", exc)
            return {
                "success": False,
                "partial": False,
                "questions": [],
                "message": f"Loi khi tao quiz: {str(exc)}",
                "sources": sources,
                "error": str(exc),
                "num_questions_requested": num_questions,
                "num_questions_generated": 0,
            }

    def generate_quiz(
        self,
        topic: str,
        num_questions: int = 5,
        difficulty: str = "medium",
        language: str = "vi",
        k: int = 10,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        hash_to_collection_name: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate quiz questions based on a topic.
        
        Uses a robust pipeline: dynamic token sizing → truncation detection →
        partial JSON salvage → supplement retry → batch plan B.
        
        Args:
            topic: Topic or description of what to quiz about
            num_questions: Number of questions to generate
            difficulty: Difficulty level - "easy", "medium", or "hard"
            language: "vi" for Vietnamese prompt, "en" for English
            k: Number of documents to retrieve for context
            target_file_hashes: File hashes to scope retrieval
            user_id: User ID to scope retrieval
            
        Returns:
            Dictionary with quiz questions and metadata
        """
        logger.info(f"Generating quiz: topic='{topic}', num_questions={num_questions}, difficulty={difficulty}")
        prepared = self.prepare_quiz_documents(
            topic=topic,
            num_questions=num_questions,
            target_file_hashes=target_file_hashes,
            user_id=user_id,
            hash_to_collection_name=hash_to_collection_name,
        )
        if not prepared.get("success"):
            return prepared
        return self.generate_quiz_from_documents(
            topic=prepared["topic"],
            topics=prepared["topics"],
            raw_documents=prepared["raw_documents"],
            num_questions=num_questions,
            difficulty=difficulty,
            language=language,
        )
    
    def generate_quiz_multi_topics(
        self,
        topics: List[str],
        num_questions: int = 10,
        difficulty: str = "medium",
        language: str = "vi",
        k: int = 8,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        hash_to_collection_name: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Generate quiz questions based on multiple topics.
        
        This method retrieves documents for each topic and combines them
        to generate a comprehensive quiz covering all selected topics.
        
        Args:
            topics: List of topics to generate questions about
            num_questions: Total number of questions to generate
            difficulty: Difficulty level - "easy", "medium", or "hard"
            language: "vi" for Vietnamese prompt, "en" for English
            k: Number of documents to retrieve per topic
            target_file_hashes: File hashes to scope retrieval
            user_id: User ID to scope retrieval
            
        Returns:
            Dictionary with quiz questions and metadata
        """
        logger.info(f"Generating multi-topic quiz: topics={topics}, num_questions={num_questions}")
        prepared = self.prepare_quiz_documents(
            topics=topics,
            num_questions=num_questions,
            target_file_hashes=target_file_hashes,
            user_id=user_id,
            hash_to_collection_name=hash_to_collection_name,
        )
        if not prepared.get("success"):
            return prepared
        return self.generate_quiz_from_documents(
            topic=prepared["topic"],
            topics=prepared["topics"],
            raw_documents=prepared["raw_documents"],
            num_questions=num_questions,
            difficulty=difficulty,
            language=language,
        )

    def prepare_quiz_documents(
        self,
        topic: Optional[str] = None,
        topics: Optional[List[str]] = None,
        num_questions: int = 5,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
        hash_to_collection_name: Optional[Dict[str, str]] = None,
        # ---- V1 course-level domain knowledge extensions ----
        roles_by_hash: Optional[Dict[str, str]] = None,
        language_by_hash: Optional[Dict[str, str]] = None,
        domain_quota_ratio: Optional[float] = None,
        groq_api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Retrieve and normalize quiz documents without invoking the LLM."""
        topic_list = [item for item in (topics or []) if str(item or "").strip()]
        if not topic_list and topic and str(topic).strip():
            topic_list = [str(topic).strip()]
        if not topic_list:
            return {
                "success": False,
                "partial": False,
                "questions": [],
                "message": "Cần có ít nhất một chủ đề",
                "sources": [],
            }

        # ── V1: prepare extras for the role-aware retriever ─────────────
        translation_cache: Dict[str, str] = {}
        topic_language: Optional[str] = None
        llm_for_translation = None
        if language_by_hash:
            try:
                from .lang_utils import detect_topic_language
                # Use the joined topics as a representative query for language
                # detection (cheap, deterministic).
                joined = " | ".join(topic_list)
                topic_language = detect_topic_language(joined)
            except Exception as exc:
                logger.warning("topic language detection failed: %s", exc)
                topic_language = None
            # Build a translation LLM (lazy); reuse the generator's LLM unless
            # a fresh key was supplied.
            if topic_language and any(
                lang and lang != "mixed" and lang != topic_language
                for lang in language_by_hash.values()
            ):
                try:
                    if groq_api_key:
                        from .llm_providers import LLMFactory as _LLMFactory
                        llm_for_translation = _LLMFactory.create(groq_api_key=groq_api_key)
                    else:
                        llm_for_translation = self.llm_provider
                except Exception as exc:
                    logger.warning("translation LLM init failed: %s", exc)
                    llm_for_translation = None

        retrieval_extras: Dict[str, Any] = {
            "roles_by_hash": roles_by_hash,
            "language_by_hash": language_by_hash,
            "topic_language": topic_language,
            "domain_quota_ratio": domain_quota_ratio,
            "translation_cache": translation_cache,
            "llm_for_translation": llm_for_translation,
        }

        if len(topic_list) == 1:
            retrieval_topic = topic_list[0]
            raw_budget = self._raw_pool_budget(num_questions)
            raw_documents = self._retrieve_documents_with_budget(
                query=retrieval_topic,
                max_total_docs=raw_budget,
                target_file_hashes=target_file_hashes,
                user_id=user_id,
                hash_to_collection_name=hash_to_collection_name,
                **retrieval_extras,
            )
            raw_documents = self._annotate_documents(raw_documents, retrieval_topic=retrieval_topic)
            if not raw_documents:
                logger.warning("No documents retrieved for topic")
                return {
                    "success": False,
                    "partial": False,
                    "questions": [],
                    "message": f"Không tìm thấy nội dung về '{retrieval_topic}' trong tài liệu",
                    "sources": [],
                }

            raw_documents = self._dedupe_documents(raw_documents)
            if not raw_documents:
                return {
                    "success": False,
                    "partial": False,
                    "questions": [],
                    "message": "Context rỗng, không thể tạo quiz",
                    "sources": [],
                }

            return {
                "success": True,
                "topic": retrieval_topic,
                "topics": topic_list,
                "raw_documents": raw_documents,
                "raw_document_count": len(raw_documents),
            }

        raw_budget = self._raw_pool_budget(num_questions)
        topic_budgets = self._allocate_topic_budgets(
            topics=topic_list,
            raw_budget=raw_budget,
            target_file_hashes=target_file_hashes,
            user_id=user_id,
        )

        all_documents: List[Document] = []
        for retrieval_topic in topic_list:
            topic_budget = topic_budgets.get(retrieval_topic, 1)
            if topic_budget <= 0:
                continue
            topic_documents = self._retrieve_documents_with_budget(
                query=retrieval_topic,
                max_total_docs=topic_budget,
                target_file_hashes=target_file_hashes,
                user_id=user_id,
                hash_to_collection_name=hash_to_collection_name,
                **retrieval_extras,
            )
            topic_documents = self._annotate_documents(
                topic_documents,
                retrieval_topic=retrieval_topic,
            )
            if topic_documents:
                all_documents.extend(topic_documents)
                logger.info(
                    "Retrieved %s documents for topic '%s' with budget=%s",
                    len(topic_documents),
                    retrieval_topic,
                    topic_budget,
                )

        if not all_documents:
            logger.warning("No documents retrieved for any topic")
            return {
                "success": False,
                "partial": False,
                "questions": [],
                "message": f"Không tìm thấy nội dung về các chủ đề: {', '.join(topic_list)}",
                "sources": [],
            }

        unique_documents = self._dedupe_documents(all_documents)
        logger.info(f"Total unique documents in raw pool: {len(unique_documents)}")
        if not unique_documents:
            return {
                "success": False,
                "partial": False,
                "questions": [],
                "message": "Context rỗng, không thể tạo quiz",
                "sources": [],
            }

        return {
            "success": True,
            "topic": ", ".join(topic_list),
            "topics": topic_list,
            "raw_documents": unique_documents,
            "raw_document_count": len(unique_documents),
        }

    def generate_quiz_from_documents(
        self,
        *,
        topic: str,
        topics: Optional[List[str]],
        raw_documents: List[Document],
        num_questions: int,
        difficulty: str = "medium",
        language: str = "vi",
    ) -> Dict[str, Any]:
        """Generate quiz questions from already-retrieved documents."""
        prepared_topics = topics or [topic]
        result = self._generate_quiz_core_vnext(
            topic=topic,
            num_questions=num_questions,
            difficulty=difficulty,
            language=language,
            raw_documents=raw_documents,
            topics=prepared_topics,
            raw_document_count=len(raw_documents),
        )
        if result.get("success") and len(prepared_topics) > 1:
            result["topics_used"] = prepared_topics
        return result
    
    def _parse_quiz_response(self, content: str) -> Optional[Dict]:
        """Parse JSON response from LLM."""
        try:
            # Try direct JSON parse
            return json.loads(content)
        except json.JSONDecodeError:
            pass
        
        # Try to extract JSON from markdown code block
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass
        
        # Try to find JSON object in content
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        
        logger.error(f"Could not parse JSON from response: {content[:200]}")
        return None
    
    def _format_quiz(self, quiz_list: List[Dict]) -> List[Dict]:
        """Format and validate quiz questions."""
        formatted = []
        
        for i, q in enumerate(quiz_list):
            try:
                # Validate required fields
                if not q.get("question"):
                    logger.warning(f"Question {i} missing 'question' field")
                    continue
                
                if not q.get("options"):
                    logger.warning(f"Question {i} missing 'options' field")
                    continue

                option_values = self._normalize_option_values(q.get("options"))
                if not option_values:
                    logger.warning("Question %s: options could not be normalized", i)
                    continue

                correct_index = self._resolve_correct_index(q, option_values)
                if correct_index is None:
                    logger.warning("Question %s: could not resolve correct answer", i)
                    continue

                structural_ok, structural_reason = validate_mcq_structure(
                    q["question"], option_values, correct_index
                )
                if not structural_ok:
                    logger.warning(
                        "Question %s rejected by MCQ validator: reason=%s",
                        i,
                        structural_reason,
                    )
                    continue

                options_dict, correct = self._stable_shuffle_options(
                    question_text=q["question"],
                    option_values=option_values,
                    correct_index=correct_index,
                )

                formatted.append({
                    "question_number": i + 1,
                    "question": q["question"],
                    "options": options_dict,
                    "correct_answer": correct,
                })

                logger.debug(f"Formatted question {i+1}: {q['question'][:50]}...")
                continue
                
                options = q.get("options", [])
                
                # Handle if options is already a dict
                if isinstance(options, dict):
                    # Already in {A: ..., B: ..., C: ..., D: ...} format
                    options_dict = options
                else:
                    # Convert list to dict
                    if not isinstance(options, list):
                        logger.warning(f"Question {i}: options is not list or dict: {type(options)}")
                        continue
                    
                    if len(options) != 4:
                        logger.warning(f"Question {i}: options has {len(options)} items, expected 4")
                        # Pad or trim to 4 options
                        while len(options) < 4:
                            options.append(f"Đáp án {chr(65 + len(options))}")
                        options = options[:4]
                    
                    options_dict = {
                        "A": options[0],
                        "B": options[1],
                        "C": options[2],
                        "D": options[3]
                    }
                
                # Get correct answer
                correct = q.get("correct_answer", "A").upper()
                if correct not in ["A", "B", "C", "D"]:
                    logger.warning(f"Question {i}: invalid correct_answer '{correct}', defaulting to 'A'")
                    correct = "A"
                
                formatted.append({
                    "question_number": i + 1,
                    "question": q["question"],
                    "options": options_dict,
                    "correct_answer": correct,
                })
                
                logger.debug(f"Formatted question {i+1}: {q['question'][:50]}...")
                
            except Exception as e:
                logger.warning(f"Error formatting question {i}: {e}")
                continue
        
        return formatted
    
    # ===== Robust Quiz Generation Helpers =====
    
    def _get_finish_reason(self, response) -> Optional[str]:
        """Extract finish_reason from LLM response metadata."""
        try:
            if hasattr(response, 'response_metadata'):
                metadata = response.response_metadata
                # Groq/OpenAI format
                if 'finish_reason' in metadata:
                    return metadata['finish_reason']
                # Some providers nest it in choices
                if 'choices' in metadata and metadata['choices']:
                    return metadata['choices'][0].get('finish_reason')
            return None
        except Exception:
            return None
    
    def _salvage_partial_json(self, content: str) -> Optional[Dict]:
        """
        Try to salvage quiz questions from truncated JSON output.
        
        Uses bracket-matching to find complete question objects
        even when the overall JSON is broken due to token limit truncation.
        """
        logger.warning("Attempting to salvage partial JSON from truncated output...")
        
        # Find the quiz array start
        quiz_start = content.find('"quiz"')
        if quiz_start == -1:
            logger.warning("No 'quiz' key found in truncated output")
            return None
        
        array_start = content.find('[', quiz_start)
        if array_start == -1:
            logger.warning("No quiz array found in truncated output")
            return None
        
        # Extract individual complete question objects using bracket matching
        questions = []
        i = array_start + 1
        
        while i < len(content):
            # Skip whitespace and commas
            while i < len(content) and content[i] in ' \t\n\r,':
                i += 1
            
            if i >= len(content) or content[i] == ']':
                break
            
            if content[i] == '{':
                # Find matching closing brace using depth counter
                depth = 0
                start = i
                found_match = False
                
                for j in range(i, len(content)):
                    if content[j] == '{':
                        depth += 1
                    elif content[j] == '}':
                        depth -= 1
                        if depth == 0:
                            # Found a complete object
                            obj_str = content[start:j + 1]
                            try:
                                q = json.loads(obj_str)
                                if q.get("question") and q.get("options"):
                                    questions.append(q)
                            except json.JSONDecodeError:
                                pass
                            i = j + 1
                            found_match = True
                            break
                
                if not found_match:
                    # No matching brace - rest is truncated
                    break
            else:
                break
        
        if questions:
            logger.info(f"Salvaged {len(questions)} complete questions from truncated output")
            return {"quiz": questions, "message": "partial_salvage"}
        
        logger.warning("No complete question objects found in truncated output")
        return None
    
    def _get_reduced_prompt(self, language: str) -> ChatPromptTemplate:
        """Get prompt variant that instructs shorter explanations to save output tokens."""
        return self._build_main_prompt(language, reduced=True)
        if language == "vi":
            template = QUIZ_GENERATION_PROMPT.replace(
                "Giải thích ngắn gọn (1-2 câu), trích dẫn từ context nếu có thể",
                "Giải thích CỰC KỲ ngắn gọn (TỐI ĐA 5-8 từ). Ưu tiên ĐỦ SỐ LƯỢNG câu hỏi."
            )
        else:
            template = QUIZ_GENERATION_PROMPT_V2.replace(
                "Keep explanations brief (1-2 sentences)",
                "Keep explanations EXTREMELY brief (MAX 5-8 words). Prioritize reaching the required question count."
            )
        return ChatPromptTemplate.from_template(template)
    
    def _generate_supplement_questions(
        self,
        context: str,
        topic: str,
        difficulty: str,
        language: str,
        existing_questions: List[Dict],
        additional_count: int,
    ) -> List[Dict]:
        """
        Generate additional questions to supplement an incomplete quiz.
        
        Args:
            context: Document content
            topic: Quiz topic
            difficulty: Difficulty level
            language: Language for prompt
            existing_questions: Already generated questions (to avoid duplicates)
            additional_count: Number of additional questions needed
            
        Returns:
            List of formatted supplement questions
        """
        logger.info(f"Generating {additional_count} supplement questions...")
        
        # Format existing questions as text for the prompt
        existing_text = "\n".join([
            f"{i + 1}. {q['question']}"
            for i, q in enumerate(existing_questions)
        ])
        
        prompt = self.supplement_prompt_vi if language == "vi" else self.supplement_prompt_en
        
        # Use moderate max_tokens for supplement
        supplement_max_tokens = max(2048, additional_count * 400 + 200)
        llm_json = self._llm_provider.get_llm(json_mode=True, max_tokens=supplement_max_tokens)
        chain = prompt | llm_json
        
        try:
            response = chain.invoke({
                "context": context,
                "topic": topic,
                "difficulty": difficulty,
                "existing_questions": existing_text,
                "additional_count": additional_count,
            })
            
            content = response.content if hasattr(response, 'content') else str(response)
            logger.info(f"Supplement response length: {len(content)} chars")
            
            quiz_data = self._parse_quiz_response(content)
            
            if quiz_data and quiz_data.get("quiz"):
                supplement = self._format_quiz(quiz_data["quiz"])
                logger.info(f"Got {len(supplement)} supplement questions")
                return supplement
            
            # Try salvage if parse failed
            quiz_data = self._salvage_partial_json(content)
            if quiz_data and quiz_data.get("quiz"):
                supplement = self._format_quiz(quiz_data["quiz"])
                logger.info(f"Salvaged {len(supplement)} supplement questions")
                return supplement
            
            logger.warning("Supplement generation returned no valid questions")
            return []
            
        except Exception as e:
            logger.error(f"Error generating supplement questions: {e}")
            return []
    
    def _generate_quiz_batched(
        self,
        context: str,
        topic: str,
        num_questions: int,
        difficulty: str,
        language: str,
        blueprint_section: Optional[str] = None,
    ) -> List[Dict]:
        """
        Generate quiz in batches when single call fails to produce enough questions.
        
        Splits the request into 2 batches, generates separately, and merges results.
        Used as a fallback (Plan B) when the primary generation is significantly short.
        
        Args:
            context: Document content
            topic: Quiz topic
            num_questions: Total questions needed
            difficulty: Difficulty level
            language: Language for prompt
            
        Returns:
            List of formatted and deduplicated questions
        """
        logger.info(f"Batch generation: splitting {num_questions} questions into 2 batches")
        
        batch1_count = (num_questions + 1) // 2  # Ceiling division
        batch2_count = num_questions - batch1_count
        
        prompt = self.prompt_vi if language == "vi" else self.prompt_en
        blueprint_section = blueprint_section or self._default_blueprint_section()
        batch_max_tokens = max(4096, batch1_count * 400 + 200)
        
        all_questions = []
        
        for batch_num, batch_count in enumerate([batch1_count, batch2_count], 1):
            try:
                logger.info(f"Batch {batch_num}: generating {batch_count} questions...")
                
                llm_json = self._llm_provider.get_llm(json_mode=True, max_tokens=batch_max_tokens)
                chain = prompt | llm_json
                
                response = chain.invoke({
                    "context": context,
                    "topic": topic,
                    "num_questions": batch_count,
                    "difficulty": difficulty,
                    "blueprint_section": blueprint_section,
                })
                
                content = response.content if hasattr(response, 'content') else str(response)
                quiz_data = self._parse_quiz_response(content)
                
                if not quiz_data:
                    quiz_data = self._salvage_partial_json(content)
                
                if quiz_data and quiz_data.get("quiz"):
                    batch_questions = self._format_quiz(quiz_data["quiz"])
                    all_questions.extend(batch_questions)
                    logger.info(f"Batch {batch_num}: got {len(batch_questions)} questions")
                else:
                    logger.warning(f"Batch {batch_num}: no valid questions returned")
                    
            except Exception as e:
                logger.error(f"Batch {batch_num} failed: {e}")
        
        # Deduplicate by checking question text similarity
        seen_questions = set()
        unique_questions = []
        for q in all_questions:
            q_text = q["question"].strip().lower()[:100]
            if q_text not in seen_questions:
                seen_questions.add(q_text)
                unique_questions.append(q)
        
        logger.info(f"Batch generation complete: {len(unique_questions)} unique questions")
        return unique_questions
    
    def _generate_quiz_core(
        self,
        topic: str,
        num_questions: int,
        difficulty: str,
        language: str,
        raw_documents: List[Document],
        topics: Optional[List[str]] = None,
        raw_document_count: int = 0,
    ) -> Dict[str, Any]:
        """
        Core quiz generation with robust retry, salvage, and batching logic.
        
        Pipeline:
        1. Calculate dynamic max_tokens based on num_questions
        2. Call LLM with appropriate prompt
        3. Check finish_reason for truncation
        4. If truncated: retry with reduced explanation + higher max_tokens
        5. If still failing: salvage partial JSON
        6. After formatting, if count < requested:
           a. If >= 70%: supplement retry for missing questions
           b. If < 70%: batch plan B (split into 2 calls)
        7. Always retry after salvage to fill missing questions
        
        Args:
            context: Formatted document context
            topic: Quiz topic or combined topics string
            num_questions: Number of questions to generate
            difficulty: Difficulty level
            language: "vi" or "en"
            documents: Retrieved documents (for citation extraction)
            
        Returns:
            Dictionary with quiz questions and metadata
        """
        raw_documents = self._dedupe_documents(raw_documents)
        sources = self._extract_document_citations(raw_documents)
        topics = topics or [topic]
        blueprint_context_budget = min(len(raw_documents), max(12, min(24, num_questions if num_questions < 24 else 24)))
        blueprint_context_documents = self._select_context_documents(
            documents=raw_documents,
            topics=topics,
            final_budget=blueprint_context_budget,
        )
        blueprint_context = self._format_context_documents(blueprint_context_documents)
        
        try:
            logger.info(f"Generating quiz with LLM (max_tokens={dynamic_max_tokens})...")
            
            response = chain.invoke({
                "context": context,
                "topic": topic,
                "num_questions": num_questions,
                "difficulty": difficulty,
                "blueprint_section": blueprint_section,
            })
            
            # Extract response content
            content = response.content if hasattr(response, 'content') else str(response)
            logger.info(f"Raw LLM response length: {len(content)} chars")
            logger.debug(f"Raw LLM response: {content[:500]}...")
            
            # Check for truncation
            finish_reason = self._get_finish_reason(response)
            was_truncated = finish_reason == "length"
            
            if was_truncated:
                logger.warning("LLM output was truncated (finish_reason=length)")
            
            # Parse response
            quiz_data = self._parse_quiz_response(content)
            
            # If parse failed and was truncated, try salvage
            if not quiz_data and was_truncated:
                quiz_data = self._salvage_partial_json(content)
            
            # If parse still failed, retry with reduced explanation + higher max_tokens
            if not quiz_data:
                logger.warning("Parse failed, retrying with reduced explanation prompt...")
                retry_max_tokens = dynamic_max_tokens + 2048
                llm_json_retry = self._llm_provider.get_llm(json_mode=True, max_tokens=retry_max_tokens)
                
                reduced_prompt = self._get_reduced_prompt(language)
                chain_retry = reduced_prompt | llm_json_retry
                
                try:
                    response_retry = chain_retry.invoke({
                        "context": context,
                        "topic": topic,
                        "num_questions": num_questions,
                        "difficulty": difficulty,
                        "blueprint_section": blueprint_section,
                    })
                    content_retry = response_retry.content if hasattr(response_retry, 'content') else str(response_retry)
                    quiz_data = self._parse_quiz_response(content_retry)
                    
                    if not quiz_data:
                        quiz_data = self._salvage_partial_json(content_retry)
                except Exception as retry_err:
                    logger.error(f"Retry with reduced prompt also failed: {retry_err}")
            
            # If all parsing attempts failed, return error
            if not quiz_data:
                return {
                    "success": False,
                    "questions": [],
                    "message": "Không thể parse kết quả từ LLM sau nhiều lần thử",
                    "sources": sources,
                    "raw_response": content[:1000]
                }
            
            # Check for error message from LLM (e.g., topic not found)
            if quiz_data.get("message") and not quiz_data.get("quiz"):
                return {
                    "success": False,
                    "questions": [],
                    "message": quiz_data["message"],
                    "sources": sources
                }
            
            # Format quiz questions
            formatted_quiz = self._format_quiz(quiz_data.get("quiz", []))
            num_generated = len(formatted_quiz)
            is_partial_salvage = quiz_data.get("message") == "partial_salvage"
            
            logger.info(f"Generated {num_generated}/{num_questions} questions (salvaged={is_partial_salvage})")
            
            # Handle insufficient questions
            if num_generated < num_questions and num_generated > 0:
                missing = num_questions - num_generated
                
                # Try supplement retry first (for small gaps or salvage results)
                if missing <= num_questions * 0.3 or is_partial_salvage:
                    logger.info(f"Supplement retry: requesting {missing} additional questions...")
                    supplement = self._generate_supplement_questions(
                        context=context,
                        topic=topic,
                        difficulty=difficulty,
                        language=language,
                        existing_questions=formatted_quiz,
                        additional_count=missing,
                    )
                    if supplement:
                        still_missing = num_questions - len(formatted_quiz)
                        formatted_quiz.extend(supplement[:still_missing])
                        logger.info(f"After supplement: {len(formatted_quiz)}/{num_questions} questions")
                
                # If still significantly short (< 70%), try batch plan B
                if len(formatted_quiz) < num_questions * 0.7:
                    logger.info(f"Batch plan B: only {len(formatted_quiz)}/{num_questions}, trying batched generation...")
                    batched_result = self._generate_quiz_batched(
                        context=context,
                        topic=topic,
                        num_questions=num_questions,
                        difficulty=difficulty,
                        language=language,
                        blueprint_section=blueprint_section,
                    )
                    if batched_result and len(batched_result) > len(formatted_quiz):
                        formatted_quiz = batched_result
                        logger.info(f"After batching: {len(formatted_quiz)}/{num_questions} questions")
            
            # Enforce exact count — truncate surplus questions
            if len(formatted_quiz) > num_questions:
                formatted_quiz = formatted_quiz[:num_questions]

            # Renumber questions sequentially
            for i, q in enumerate(formatted_quiz):
                q["question_number"] = i + 1
            
            # Build result
            final_count = len(formatted_quiz)
            warning = ""
            if final_count < num_questions:
                warning = f"Chỉ tạo được {final_count}/{num_questions} câu hỏi do context không đủ nội dung"
            
            if final_count > 0:
                logger.info(f"Sample question 1: {formatted_quiz[0]}")
            
            result = {
                "success": True,
                "questions": formatted_quiz,
                "message": warning or quiz_data.get("message", "") if quiz_data.get("message") != "partial_salvage" else warning,
                "sources": sources,
                "num_questions_requested": num_questions,
                "num_questions_generated": final_count,
            }

            return result
            
        except Exception as e:
            logger.error(f"Error generating quiz: {e}")
            return {
                "success": False,
                "questions": [],
                "message": f"Lỗi khi tạo quiz: {str(e)}",
                "sources": sources,
                "error": str(e)
            }
    
    def generate_quiz_text(
        self,
        topic: str,
        num_questions: int = 5,
        k: int = 10
    ) -> str:
        """
        Generate quiz and return as formatted text.
        
        Args:
            topic: Topic to quiz about
            num_questions: Number of questions
            k: Documents to retrieve
            
        Returns:
            Formatted quiz text
        """
        result = self.generate_quiz(topic=topic, num_questions=num_questions, k=k)
        
        if not result["success"] or not result["questions"]:
            return result.get("message", "Không thể tạo quiz")
        
        lines = [f"📝 QUIZ: {topic.upper()}", "=" * 50, ""]
        
        for q in result["questions"]:
            lines.append(f"Câu {q['question_number']}: {q['question']}")
            for letter, option in q["options"].items():
                lines.append(f"   {letter}. {option}")
            lines.append(f"   ✅ Đáp án: {q['correct_answer']}")
            lines.append("")
        
        lines.append("=" * 50)
        lines.append(f"Tổng: {len(result['questions'])} câu hỏi")
        
        return "\n".join(lines)
    
    def export_to_qti(
        self,
        questions: List[Dict[str, Any]],
        title: str = "Generated Quiz",
        description: str = ""
    ) -> str:
        """
        Export quiz questions to QTI 2.1 XML format.
        
        Args:
            questions: List of formatted quiz questions
            title: Quiz title
            description: Quiz description
            
        Returns:
            QTI XML string
        """
        # Create root element
        root = ET.Element('questestinterop')
        root.set('xmlns', 'http://www.imsglobal.org/xsd/ims_qtiasiv1p2')
        root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
        root.set('xsi:schemaLocation', 'http://www.imsglobal.org/xsd/ims_qtiasiv1p2 http://www.imsglobal.org/xsd/ims_qtiasiv1p2p1.xsd')
        
        # Assessment
        assessment = ET.SubElement(root, 'assessment')
        assessment.set('ident', f'quiz_{datetime.now().strftime("%Y%m%d%H%M%S")}')
        assessment.set('title', title)
        
        # Metadata
        qtimetadata = ET.SubElement(assessment, 'qtimetadata')
        qtimetadatafield = ET.SubElement(qtimetadata, 'qtimetadatafield')
        ET.SubElement(qtimetadatafield, 'fieldlabel').text = 'qmd_timelimit'
        ET.SubElement(qtimetadatafield, 'fieldentry').text = '0'
        
        # Section
        section = ET.SubElement(assessment, 'section')
        section.set('ident', 'root_section')
        section.set('title', title)
        
        if description:
            ET.SubElement(section, 'rubric').text = description
        
        # Add questions
        for q in questions:
            item = ET.SubElement(section, 'item')
            item.set('ident', f'question_{q["question_number"]}')
            item.set('title', f'Question {q["question_number"]}')
            
            # Item metadata
            itemmetadata = ET.SubElement(item, 'itemmetadata')
            qtimetadata_item = ET.SubElement(itemmetadata, 'qtimetadata')
            
            # Question type
            field1 = ET.SubElement(qtimetadata_item, 'qtimetadatafield')
            ET.SubElement(field1, 'fieldlabel').text = 'question_type'
            ET.SubElement(field1, 'fieldentry').text = 'multiple_choice_question'
            
            # Points
            field2 = ET.SubElement(qtimetadata_item, 'qtimetadatafield')
            ET.SubElement(field2, 'fieldlabel').text = 'points_possible'
            ET.SubElement(field2, 'fieldentry').text = '1.0'
            
            # Presentation
            presentation = ET.SubElement(item, 'presentation')
            material = ET.SubElement(presentation, 'material')
            mattext = ET.SubElement(material, 'mattext')
            mattext.set('texttype', 'text/html')
            mattext.text = q["question"]
            
            # Response
            response = ET.SubElement(presentation, 'response_lid')
            response.set('ident', 'response1')
            response.set('rcardinality', 'Single')
            
            render_choice = ET.SubElement(response, 'render_choice')
            
            # Options
            for key, value in q["options"].items():
                response_label = ET.SubElement(render_choice, 'response_label')
                response_label.set('ident', key)
                mat = ET.SubElement(response_label, 'material')
                mat_text = ET.SubElement(mat, 'mattext')
                mat_text.set('texttype', 'text/plain')
                mat_text.text = value
            
            # Correct answer
            resprocessing = ET.SubElement(item, 'resprocessing')
            outcomes = ET.SubElement(resprocessing, 'outcomes')
            decvar = ET.SubElement(outcomes, 'decvar')
            decvar.set('maxvalue', '100')
            decvar.set('minvalue', '0')
            decvar.set('varname', 'SCORE')
            decvar.set('vartype', 'Decimal')
            
            # Correct response condition
            respcondition = ET.SubElement(resprocessing, 'respcondition')
            respcondition.set('continue', 'No')
            conditionvar = ET.SubElement(respcondition, 'conditionvar')
            varequal = ET.SubElement(conditionvar, 'varequal')
            varequal.set('respident', 'response1')
            varequal.text = q["correct_answer"]
            
            setvar = ET.SubElement(respcondition, 'setvar')
            setvar.set('action', 'Set')
            setvar.set('varname', 'SCORE')
            setvar.text = '100'
            
        # Convert to string with pretty print
        xml_str = ET.tostring(root, encoding='unicode')
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent='  ')
        
        return "\n".join(lines)
