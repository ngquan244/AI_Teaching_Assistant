"""
Grading API routes - Exam Grading and Results
"""
import json
import logging
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import APIRouter, UploadFile, File, HTTPException

from backend.auth.dependencies import CurrentUser
from backend.schemas import GradingRequest, GradingResponse, GradingResult, GradingSummary
from backend.services import grading_service
from backend.config import settings
from backend.grader import create_processor, ExamProcessor

logger = logging.getLogger(__name__)
router = APIRouter()

# Global processor instance (initialized lazily)
_processor: Optional[ExamProcessor] = None


def get_processor() -> ExamProcessor:
    """Get or create the exam processor singleton"""
    global _processor
    if _processor is None:
        kaggle_dir = settings.PROJECT_ROOT / "kaggle"
        _processor = create_processor(
            template_path=str(kaggle_dir / "Template" / "temp.jpg"),
            student_json_path=str(kaggle_dir / "Input Materials" / "student_coords.json"),
            answer_json_path=str(kaggle_dir / "Input Materials" / "answer.json"),
            output_path=str(settings.PROJECT_ROOT / "final_result.json")
        )
    return _processor


@router.post("/execute")
async def execute_grading(user: CurrentUser):
    """Execute grading on all images in Filled-temp folder"""
    try:
        processor = get_processor()
        kaggle_dir = settings.PROJECT_ROOT / "kaggle"
        filled_dir = kaggle_dir / "Filled-temp"
        
        summary = processor.process_and_save(
            filled_dir, 
            str(settings.PROJECT_ROOT / "final_result.json")
        )
        
        return {
            "success": True,
            "total_images": summary["total_images"],
            "successful": summary["successful"],
            "failed": summary["failed"],
            "output_path": summary["output_path"]
        }
    except Exception as e:
        logger.exception("Grading execution failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/grade-single")
async def grade_single_image(user: CurrentUser, file: UploadFile = File(...)):
    """Grade a single uploaded exam image"""
    try:
        # Read image
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file")
        
        # Process
        processor = get_processor()
        result = processor.process_image(img, file.filename or "uploaded")
        
        return {
            "success": result.success,
            "result": result.to_dict()
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Single image grading failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/summary", response_model=GradingResponse)
async def summarize_exam_results(request: GradingRequest, user: CurrentUser):
    """Summarize exam results by exam code"""
    
    # Get results from database
    data = grading_service.get_results_by_exam_code(request.exam_code)
    
    # Export to Excel
    excel_file = grading_service.export_to_excel(
        exam_code=request.exam_code,
        summary=data["summary"],
        results=data["results"]
    )
    
    # Send email notification
    if excel_file:
        grading_service.send_email(
            to_email=settings.EMAIL_RECEIVER,
            subject=f"Kết quả tổng hợp mã đề {request.exam_code}",
            body=f"Đính kèm file Excel tổng hợp kết quả bài thi mã đề {request.exam_code}.",
            attachment=excel_file
        )
    
    # Convert to response model
    summary = GradingSummary(**data["summary"])
    results = [GradingResult(**r) for r in data["results"]]
    
    return GradingResponse(
        success=True,
        exam_code=request.exam_code,
        summary=summary,
        overall_assessment=data["overall_assessment"],
        results=results,
        excel_file=excel_file
    )


@router.get("/results")
async def get_all_results(user: CurrentUser):
    """Get all grading results from JSON file"""
    results = grading_service.get_results_from_json()
    
    if not results:
        return {
            "success": False,
            "results": [],
            "message": "Chưa có kết quả chấm điểm"
        }
    
    return {"success": True, "results": results}
