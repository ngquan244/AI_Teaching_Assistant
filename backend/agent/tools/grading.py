"""
Grading Tool
Handles exam grading using SIFT/OpenCV image processing.
"""

import json
from typing import Optional, Type, Dict, Any, List
from pathlib import Path

from langchain.tools import BaseTool
from pydantic import BaseModel, Field
import pyodbc

from .base import logger
from ...core.config import settings
from ...grader import create_processor, ExamProcessor
from ...utils import get_user_upload_dir, get_user_result_path

__all__ = ["GradingTool", "GradingInput", "get_grading_tool"]


class GradingInput(BaseModel):
    """Input schema for grading tool"""
    notebook_name: str = Field(
        description="Tên file notebook cần chạy (không còn sử dụng, giữ để tương thích)",
        default="grading-timing-mark.ipynb"
    )


def _create_processor_for_user(user_id: Optional[str] = None) -> ExamProcessor:
    """
    Create an ExamProcessor with per-user output path.
    Falls back to legacy global path if no user_id.
    """
    kaggle_dir = settings.PROJECT_ROOT / "kaggle"
    
    if user_id:
        output_path = str(get_user_result_path(user_id))
    else:
        output_path = str(settings.PROJECT_ROOT / "final_result.json")
    
    return create_processor(
        template_path=str(kaggle_dir / "Template" / "temp.jpg"),
        student_json_path=str(kaggle_dir / "Input Materials" / "student_coords.json"),
        answer_json_path=str(kaggle_dir / "Input Materials" / "answer.json"),
        output_path=output_path
    )


class GradingTool(BaseTool):
    """
    Tool để chấm điểm bài thi trắc nghiệm.
    
    This tool:
    - Processes exam images using SIFT/OpenCV
    - Detects student answers
    - Calculates scores
    - Saves results to database
    """
    
    name: str = "execute_notebook"
    description: str = """
    Chấm điểm bài thi trắc nghiệm từ ảnh đã upload.
    
    Sử dụng khi người dùng yêu cầu chấm điểm bài thi.
    
    CÁCH TRẢ LỜI (BẮT BUỘC):
    
    1. Nói ngắn gọn: "Đã chấm xong X bài thi"
    
    2. Hiển thị kết quả mỗi sinh viên theo format:
    
     **Kết quả chấm điểm**
    
    **Sinh viên: [Họ tên]**
    - Mã SV: [student_id]
    - Email: [email]
    - Mã đề: [exam_code]
    - **Điểm: [score]/10**
    - Đúng: [correct] | Sai: [wrong] | Bỏ trống: [blank]
    
    3. KHÔNG viết code Python
    4. KHÔNG hướng dẫn cách đọc JSON
    5. KHÔNG giải thích cách tính điểm
    """
    args_schema: Type[BaseModel] = GradingInput
    user_id: Optional[str] = None
    
    def _run(self, notebook_name: str = "grading-timing-mark.ipynb") -> str:
        """
        Execute grading using the Python module.
        
        Args:
            notebook_name: Legacy parameter for compatibility
            
        Returns:
            JSON string with grading results or error
        """
        try:
            # Update JSON from database
            try:
                self._update_json_from_db()
            except Exception as dbjson_err:
                logger.error(f"Error updating JSON from DB: {str(dbjson_err)}")
                return json.dumps({
                    "error": "Lỗi khi cập nhật answer.json/student_coords.json từ DB",
                    "detail": str(dbjson_err)
                }, ensure_ascii=False, indent=2)

            logger.info("Starting grading using Python module")
            
            # Determine paths based on user context
            if self.user_id:
                filled_dir = get_user_upload_dir(self.user_id)
                output_path = get_user_result_path(self.user_id)
            else:
                kaggle_dir = settings.PROJECT_ROOT / "kaggle"
                filled_dir = kaggle_dir / "Filled-temp"
                output_path = settings.PROJECT_ROOT / "final_result.json"
            
            # Check if images exist
            if not filled_dir.exists():
                return json.dumps({
                    "error": f"Thư mục upload không tồn tại: {filled_dir}",
                    "hint": "Vui lòng upload ảnh bài thi trước khi chấm điểm"
                }, ensure_ascii=False, indent=2)
            
            # Get or create processor
            try:
                processor = _create_processor_for_user(self.user_id)
            except FileNotFoundError as e:
                return json.dumps({
                    "error": f"Không thể khởi tạo processor: {str(e)}",
                    "hint": "Kiểm tra template image và JSON files"
                }, ensure_ascii=False, indent=2)
            
            # Process all images
            logger.info(f"Processing images in: {filled_dir}")
            summary = processor.process_and_save(filled_dir, str(output_path))
            
            logger.info(f"Grading completed: {summary['successful']}/{summary['total_images']} successful")
            
            # Read results from output file
            result_data = self._read_results(output_path)
            
            # Save to database
            try:
                if isinstance(result_data, dict) and "results" in result_data:
                    self._save_results_to_db(result_data["results"])
            except Exception as db_err:
                logger.error(f"Error saving results to DB: {str(db_err)}")
            
            # Format output for agent
            graded_results = result_data.get("results", []) if isinstance(result_data, dict) else []
            
            response = {
                "success": True,
                "message": f"Đã chấm điểm {summary['successful']}/{summary['total_images']} bài thi thành công",
                "total_images": summary["total_images"],
                "successful": summary["successful"],
                "failed": summary["failed"],
            }
            
            # Add individual results
            students_results = []
            for r in graded_results:
                if r.get("success", False):
                    students_results.append({
                        "student_id": r.get("student_id"),
                        "name": r.get("name"),
                        "email": r.get("email"),
                        "exam_code": r.get("exam_code"),
                        "score": r.get("score"),
                        "correct": r.get("correct"),
                        "wrong": r.get("wrong"),
                        "blank": r.get("blank"),
                        "total_questions": r.get("total_questions")
                    })
                else:
                    students_results.append({
                        "image_name": r.get("image_name"),
                        "error": r.get("error"),
                        "suggestion": r.get("suggestion")
                    })
            
            response["students"] = students_results
            
            return json.dumps(response, ensure_ascii=False, indent=2)
            
        except Exception as e:
            logger.error(f"Exception in _run(): {str(e)}")
            logger.exception(e)
            return json.dumps({
                "error": str(e),
                "type": type(e).__name__,
                "hint": "Kiểm tra ảnh và dependencies"
            }, ensure_ascii=False, indent=2)
    
    def _read_results(self, result_path: Path) -> Dict[str, Any]:
        """
        Read results from JSON file.
        
        Args:
            result_path: Path to result JSON file
            
        Returns:
            Dictionary with results or error
        """
        try:
            if result_path.exists():
                with open(result_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {"error": "Không tìm thấy file kết quả"}
        except Exception as e:
            return {"error": f"Không thể đọc kết quả: {str(e)}"}
    
    def _update_json_from_db(self) -> None:
        """
        Fetch data from DB and update JSON files:
        - answer.json
        - student_coords.json
        """
        conn = pyodbc.connect(settings.SQL_SERVER_CONN_STR)
        cursor = conn.cursor()

        # Fetch exams and answers
        cursor.execute("""
            SELECT id, exam_code, question_count
            FROM exams
        """)
        exams = cursor.fetchall()

        answer_json = []

        for exam in exams:
            exam_id = exam.id
            exam_code = exam.exam_code
            question_count = exam.question_count

            cursor.execute("""
                SELECT question_number, correct_answer
                FROM exam_answers
                WHERE exam_id = ?
                ORDER BY question_number ASC
            """, exam_id)

            answers = [
                {
                    "question": row.question_number,
                    "answer": row.correct_answer
                }
                for row in cursor.fetchall()
            ]

            answer_json.append({
                "exam_code": exam_code,
                "question_count": question_count,
                "answers": answers
            })

        # Fetch students
        cursor.execute("""
            SELECT student_id, email, full_name, student_code
            FROM students
        """)
        students = cursor.fetchall()

        student_coords_json = [
            {
                "student_id": stu.student_id,
                "name": stu.full_name,
                "email": stu.email,
                "coords": stu.student_code
            }
            for stu in students
        ]

        cursor.close()
        conn.close()

        # Save JSON files
        kaggle_input_dir = settings.PROJECT_ROOT / "kaggle" / "Input Materials"
        kaggle_input_dir.mkdir(parents=True, exist_ok=True)

        answer_path = kaggle_input_dir / "answer.json"
        student_coords_path = kaggle_input_dir / "student_coords.json"

        with open(answer_path, "w", encoding="utf-8") as f:
            json.dump(answer_json, f, ensure_ascii=False, indent=2)

        with open(student_coords_path, "w", encoding="utf-8") as f:
            json.dump(student_coords_json, f, ensure_ascii=False, indent=2)

    async def _arun(self, notebook_name: str = "grading-timing-mark.ipynb") -> str:
        """Execute tool asynchronously"""
        return self._run(notebook_name)

    def _save_results_to_db(self, results: List[Dict[str, Any]]) -> None:
        """
        Save grading results to database.
        
        Args:
            results: List of grading results
        """
        if not results:
            return

        conn = pyodbc.connect(settings.SQL_SERVER_CONN_STR)
        cursor = conn.cursor()

        sql_check_student = """
        SELECT 1 FROM students WHERE student_id = ?
        """

        sql_result = """
        MERGE dbo.final_results AS target
        USING (
            SELECT ?, ?, ?, ?, ?, ?, ?
        ) AS source (
            student_id,
            exam_code,
            total_questions,
            correct,
            wrong,
            blank,
            score
        )
        ON target.student_id = source.student_id
        AND target.exam_code = source.exam_code

        WHEN MATCHED THEN
            UPDATE SET
                total_questions = source.total_questions,
                correct = source.correct,
                wrong = source.wrong,
                blank = source.blank,
                score = source.score

        WHEN NOT MATCHED THEN
            INSERT (
                student_id,
                exam_code,
                total_questions,
                correct,
                wrong,
                blank,
                score
            )
            VALUES (
                source.student_id,
                source.exam_code,
                source.total_questions,
                source.correct,
                source.wrong,
                source.blank,
                source.score
            );
        """

        for r in results:
            cursor.execute(sql_check_student, r["student_id"])
            if cursor.fetchone() is None:
                logger.error(
                    f"Skip result: student_id NOT FOUND → {r['student_id']}"
                )
                continue

            cursor.execute(
                sql_result,
                r["student_id"],
                r["exam_code"],
                int(r["total_questions"]),
                int(r["correct"]),
                int(r["wrong"]),
                int(r["blank"]),
                float(r["score"])
            )

        conn.commit()
        cursor.close()
        conn.close()


def get_grading_tool(user_id: Optional[str] = None) -> GradingTool:
    """
    Factory function to create grading tool.
    
    Args:
        user_id: Optional user ID for per-user workspace isolation
    
    Returns:
        GradingTool instance
    """
    return GradingTool(user_id=user_id)


# Alias for backward compatibility
def get_notebook_tool(user_id: Optional[str] = None) -> GradingTool:
    """Alias for get_grading_tool for backward compatibility"""
    return get_grading_tool(user_id=user_id)
