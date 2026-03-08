"""
Grading Tasks
=============
Celery tasks for exam grading operations.
These tasks run in the 'misc' queue.
"""
import logging
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

from celery import shared_task

from backend.celery_app import BaseTaskWithRetry
from backend.services.job_service import get_sync_job_service

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.grading_tasks.grade_batch",
    queue="misc",
    max_retries=2,
    soft_time_limit=600,
    time_limit=900,
)
def grade_batch(
    self,
    job_id: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Execute batch grading on all images in user's upload folder.
    
    Args:
        job_id: Job ID for tracking
        user_id: User ID for per-user workspace isolation (required)
    """
    from backend.core.config import settings
    from backend.grader import create_processor
    from backend.utils import get_user_upload_dir, get_user_result_path
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        if not user_id:
            raise ValueError("user_id is required for grade_batch task")
        
        job_service.start_job(job_uuid, "Initializing grader")
        
        kaggle_dir = settings.PROJECT_ROOT / "kaggle"
        filled_dir = get_user_upload_dir(user_id)
        output_path = str(get_user_result_path(user_id))
        
        # Create processor with per-user output path
        processor = create_processor(
            template_path=str(kaggle_dir / "Template" / "temp.jpg"),
            student_json_path=str(kaggle_dir / "Input Materials" / "student_coords.json"),
            answer_json_path=str(kaggle_dir / "Input Materials" / "answer.json"),
            output_path=output_path,
        )
        
        # Count images for progress tracking
        image_files = list(filled_dir.glob("*.jpg")) + list(filled_dir.glob("*.png"))
        total_images = len(image_files)
        
        if total_images == 0:
            result = {
                "success": False,
                "error": "No images found in user's upload folder",
                "total_images": 0,
            }
            job_service.fail_job(job_uuid, result["error"])
            return result
        
        job_service.update_progress(job_uuid, 10, f"Processing {total_images} images")
        
        # Process all images
        summary = processor.process_and_save(filled_dir, output_path)
        
        result = {
            "success": True,
            "total_images": summary.get("total_images", total_images),
            "successful": summary.get("successful", 0),
            "failed": summary.get("failed", 0),
            "output_path": summary.get("output_path"),
        }
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in grade_batch task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.grading_tasks.grade_single",
    queue="misc",
    max_retries=2,
    soft_time_limit=60,
    time_limit=120,
)
def grade_single(
    self,
    job_id: str,
    image_data: bytes,
    filename: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Grade a single exam image.
    
    Args:
        job_id: Job ID for tracking
        image_data: Raw image bytes
        filename: Original filename
        user_id: User ID for per-user workspace isolation (required)
    """
    import cv2
    import numpy as np
    from backend.core.config import settings
    from backend.grader import create_processor
    from backend.utils import get_user_result_path
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        if not user_id:
            raise ValueError("user_id is required for grade_single task")
        
        job_service.start_job(job_uuid, f"Grading {filename}")
        
        # Decode image
        nparr = np.frombuffer(image_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        
        if img is None:
            result = {"success": False, "error": "Invalid image file"}
            job_service.fail_job(job_uuid, result["error"])
            return result
        
        # Create processor with per-user output path
        kaggle_dir = settings.PROJECT_ROOT / "kaggle"
        output_path = str(get_user_result_path(user_id))
        processor = create_processor(
            template_path=str(kaggle_dir / "Template" / "temp.jpg"),
            student_json_path=str(kaggle_dir / "Input Materials" / "student_coords.json"),
            answer_json_path=str(kaggle_dir / "Input Materials" / "answer.json"),
            output_path=output_path,
        )
        
        # Process image
        grading_result = processor.process_image(img, filename)
        
        result = {
            "success": grading_result.success,
            "result": grading_result.to_dict(),
        }
        
        if grading_result.success:
            job_service.complete_job(job_uuid, result)
        else:
            job_service.fail_job(job_uuid, "Grading failed")
        
        return result
        
    except Exception as e:
        logger.exception(f"Error in grade_single task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.grading_tasks.generate_report",
    queue="misc",
    max_retries=2,
)
def generate_report(
    self,
    job_id: str,
    exam_code: str,
    send_email: bool = True,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate grading summary report and optionally send via email.
    
    Args:
        job_id: Job ID for tracking
        exam_code: Exam code to filter results
        send_email: Whether to send email notification
    """
    from backend.services import grading_service
    from backend.core.config import settings
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Generating report for {exam_code}")
        
        # Get results from database
        job_service.update_progress(job_uuid, 20, "Fetching results")
        data = grading_service.get_results_by_exam_code(exam_code)
        
        # Export to Excel
        job_service.update_progress(job_uuid, 50, "Creating Excel report")
        excel_file = grading_service.export_to_excel(
            exam_code=exam_code,
            summary=data["summary"],
            results=data["results"],
        )
        
        # Send email if requested
        if send_email and excel_file:
            job_service.update_progress(job_uuid, 80, "Sending email")
            grading_service.send_email(
                to_email=settings.EMAIL_RECEIVER,
                subject=f"Kết quả tổng hợp mã đề {exam_code}",
                body=f"Đính kèm file Excel tổng hợp kết quả bài thi mã đề {exam_code}.",
                attachment=excel_file,
            )
        
        result = {
            "success": True,
            "exam_code": exam_code,
            "summary": data["summary"],
            "overall_assessment": data.get("overall_assessment"),
            "excel_file": excel_file,
            "results_count": len(data["results"]),
        }
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in generate_report task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()
