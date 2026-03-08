"""
Quiz Generator Module
=====================
Generate quiz questions from documents using RAG + configurable LLM backends.
Supports Ollama (local) and Groq Cloud (API) with strict JSON output.
"""

import logging
import json
import re
import xml.etree.ElementTree as ET
from xml.dom import minidom
from typing import List, Dict, Any, Optional
from datetime import datetime

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from .config import rag_config
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
        base_url: Optional[str] = None
    ):
        """
        Initialize Quiz Generator.
        
        Args:
            retriever: DocumentRetriever instance
            llm_provider: Pre-configured LLM provider (if None, uses LLMFactory)
            model: Model name override (legacy, for backwards compatibility)
            temperature: Generation temperature (lower = more focused)
            base_url: API base URL (legacy)
        """
        self.retriever = retriever
        
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
        self.prompt_vi = ChatPromptTemplate.from_template(QUIZ_GENERATION_PROMPT)
        self.prompt_en = ChatPromptTemplate.from_template(QUIZ_GENERATION_PROMPT_V2)
        self.supplement_prompt_vi = ChatPromptTemplate.from_template(QUIZ_SUPPLEMENT_PROMPT_VI)
        self.supplement_prompt_en = ChatPromptTemplate.from_template(QUIZ_SUPPLEMENT_PROMPT_EN)
        
        # Initialize if provider not passed
        if self._llm_provider is None:
            self._init_llm()
        
        logger.info(f"QuizGenerator initialized with provider: {self._llm_provider.provider_name}")
    
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
        return self._llm_provider.model if self._llm_provider else self._model_override or rag_config.OLLAMA_MODEL
    
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

    def generate_quiz(
        self,
        topic: str,
        num_questions: int = 5,
        difficulty: str = "medium",
        language: str = "vi",
        k: int = 10,
        target_file_hashes: Optional[List[str]] = None,
        user_id: Optional[str] = None,
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
        
        # Step 1: Retrieve relevant documents
        retrieve_kwargs: Dict[str, Any] = {"k": k}
        if hasattr(self.retriever, 'resolve_target_file_hashes'):
            retrieve_kwargs["target_file_hashes"] = target_file_hashes
            retrieve_kwargs["user_id"] = user_id
        documents = self.retriever.retrieve(topic, **retrieve_kwargs)
        
        if not documents:
            logger.warning("No documents retrieved for topic")
            return {
                "success": False,
                "questions": [],
                "message": f"Không tìm thấy nội dung về '{topic}' trong tài liệu",
                "sources": []
            }
        
        # Step 2: Format context
        context = self.retriever.format_context(documents)
        
        if not context.strip():
            return {
                "success": False,
                "questions": [],
                "message": "Context rỗng, không thể tạo quiz",
                "sources": []
            }
        
        # Step 3: Generate quiz using core method with retry/salvage/batch logic
        return self._generate_quiz_core(
            context=context,
            topic=topic,
            num_questions=num_questions,
            difficulty=difficulty,
            language=language,
            documents=documents,
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
        
        if not topics:
            return {
                "success": False,
                "questions": [],
                "message": "Cần có ít nhất một chủ đề",
                "sources": []
            }
        
        # Step 1: Retrieve documents for all topics
        all_documents = []
        all_sources = []
        k_per_topic = max(3, k // len(topics))  # Distribute k across topics
        
        retrieve_kwargs_base: Dict[str, Any] = {}
        if hasattr(self.retriever, 'resolve_target_file_hashes'):
            retrieve_kwargs_base["target_file_hashes"] = target_file_hashes
            retrieve_kwargs_base["user_id"] = user_id
        
        for topic in topics:
            documents = self.retriever.retrieve(topic, k=k_per_topic, **retrieve_kwargs_base)
            if documents:
                all_documents.extend(documents)
                logger.info(f"Retrieved {len(documents)} documents for topic: {topic}")
        
        if not all_documents:
            logger.warning("No documents retrieved for any topic")
            return {
                "success": False,
                "questions": [],
                "message": f"Không tìm thấy nội dung về các chủ đề: {', '.join(topics)}",
                "sources": []
            }
        
        # Remove duplicates (same page content)
        seen_content = set()
        unique_documents = []
        for doc in all_documents:
            content_hash = hash(doc.page_content[:200])  # Hash first 200 chars
            if content_hash not in seen_content:
                seen_content.add(content_hash)
                unique_documents.append(doc)
        
        logger.info(f"Total unique documents: {len(unique_documents)}")
        
        # Step 2: Format combined context
        context = self.retriever.format_context(unique_documents[:15])  # Limit to avoid token overflow
        
        if not context.strip():
            return {
                "success": False,
                "questions": [],
                "message": "Context rỗng, không thể tạo quiz",
                "sources": []
            }
        
        # Step 3: Create combined topic string
        topics_str = ", ".join(topics)
        
        # Step 4: Generate quiz using core method with retry/salvage/batch logic
        result = self._generate_quiz_core(
            context=context,
            topic=topics_str,
            num_questions=num_questions,
            difficulty=difficulty,
            language=language,
            documents=unique_documents,
        )
        
        if result.get("success"):
            result["topics_used"] = topics
        
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
                    "explanation": q.get("explanation", "")
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
        context: str,
        topic: str,
        num_questions: int,
        difficulty: str,
        language: str,
        documents: list,
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
        sources = self.retriever.extract_citations(documents)
        
        # Select prompt based on language
        prompt = self.prompt_vi if language == "vi" else self.prompt_en
        
        # Dynamic max_tokens: ~350-400 tokens per question + JSON overhead
        estimated_tokens = num_questions * 400 + 200
        dynamic_max_tokens = max(4096, estimated_tokens)
        
        # Get LLM with appropriate max_tokens
        llm_json = self._llm_provider.get_llm(json_mode=True, max_tokens=dynamic_max_tokens)
        chain = prompt | llm_json
        
        try:
            logger.info(f"Generating quiz with LLM (max_tokens={dynamic_max_tokens})...")
            
            response = chain.invoke({
                "context": context,
                "topic": topic,
                "num_questions": num_questions,
                "difficulty": difficulty
            })
            
            # Extract response content
            content = response.content if hasattr(response, 'content') else str(response)
            logger.info(f"Raw LLM response length: {len(content)} chars")
            logger.info(f"Raw LLM response: {content[:500]}...")
            
            # Check for truncation
            finish_reason = self._get_finish_reason(response)
            was_truncated = finish_reason == "length"
            
            if was_truncated:
                logger.warning("LLM output was truncated (finish_reason=length)")
            
            # Phase 1: Parse response
            quiz_data = self._parse_quiz_response(content)
            
            # Phase 2: If parse failed and was truncated, try salvage
            if not quiz_data and was_truncated:
                quiz_data = self._salvage_partial_json(content)
            
            # Phase 3: If parse still failed, retry with reduced explanation + higher max_tokens
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
                        "difficulty": difficulty
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
            
            # Phase 4: Format quiz questions
            formatted_quiz = self._format_quiz(quiz_data.get("quiz", []))
            num_generated = len(formatted_quiz)
            is_partial_salvage = quiz_data.get("message") == "partial_salvage"
            
            logger.info(f"Generated {num_generated}/{num_questions} questions (salvaged={is_partial_salvage})")
            
            # Phase 5: Handle insufficient questions
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
                    )
                    if batched_result and len(batched_result) > len(formatted_quiz):
                        formatted_quiz = batched_result
                        logger.info(f"After batching: {len(formatted_quiz)}/{num_questions} questions")
            
            # Phase 6: Enforce exact count — truncate surplus questions
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
            
            if warning:
                result["warning"] = warning
            
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
        result = self.generate_quiz(topic, num_questions, k)
        
        if not result["success"] or not result["quiz"]:
            return result.get("message", "Không thể tạo quiz")
        
        lines = [f"📝 QUIZ: {topic.upper()}", "=" * 50, ""]
        
        for q in result["quiz"]:
            lines.append(f"Câu {q['id']}: {q['question']}")
            for letter, option in q["options"].items():
                lines.append(f"   {letter}. {option}")
            lines.append(f"   ✅ Đáp án: {q['correct_answer']}")
            if q.get("explanation"):
                lines.append(f"   💡 Giải thích: {q['explanation']}")
            lines.append("")
        
        lines.append("=" * 50)
        lines.append(f"Tổng: {len(result['quiz'])} câu hỏi")
        
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
            
            # Feedback if explanation exists
            if q.get("explanation"):
                itemfeedback = ET.SubElement(item, 'itemfeedback')
                itemfeedback.set('ident', 'correct_fb')
                flow_mat = ET.SubElement(itemfeedback, 'flow_mat')
                material_fb = ET.SubElement(flow_mat, 'material')
                mattext_fb = ET.SubElement(material_fb, 'mattext')
                mattext_fb.set('texttype', 'text/html')
                mattext_fb.text = q["explanation"]
        
        # Convert to string with pretty print
        xml_str = ET.tostring(root, encoding='unicode')
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent='  ')
        
        return "\n".join(lines)
