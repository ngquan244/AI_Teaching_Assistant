"""
Miscellaneous Tasks
===================
Celery tasks for general utility operations.
These tasks run in the 'misc' queue.
"""
import logging
import uuid
from pathlib import Path
from typing import Optional, Dict, Any, List

from celery import shared_task

from backend.celery_app import BaseTaskWithRetry
from backend.services.job_service import get_sync_job_service

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.misc_tasks.file_download",
    queue="misc",
    max_retries=3,
)
def file_download(
    self,
    job_id: str,
    url: str,
    destination: str,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Download a file from URL to local storage.
    
    Args:
        job_id: Job ID for tracking
        url: Source URL
        destination: Local destination path
    """
    import httpx
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, "Downloading file")
        
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        with httpx.Client(timeout=120.0) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                total = int(response.headers.get("content-length", 0))
                downloaded = 0
                
                with open(dest_path, "wb") as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = int((downloaded / total) * 100)
                            job_service.update_progress(
                                job_uuid, pct, f"Downloaded {downloaded}/{total} bytes"
                            )
        
        result = {
            "success": True,
            "path": str(dest_path),
            "size": dest_path.stat().st_size,
        }
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in file_download task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.misc_tasks.send_email",
    queue="misc",
    max_retries=3,
)
def send_email(
    self,
    job_id: str,
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Send an email with optional attachment.
    
    Args:
        job_id: Job ID for tracking
        to_email: Recipient email
        subject: Email subject
        body: Email body
        attachment_path: Optional path to attachment file
    """
    import smtplib
    import ssl
    from email.message import EmailMessage
    from email.mime.base import MIMEBase
    from email import encoders
    
    from backend.core.config import settings
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Sending email to {to_email}")
        
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.EMAIL_USER
        msg["To"] = to_email
        msg.set_content(body)
        
        # Add attachment if provided
        if attachment_path:
            attach_path = Path(attachment_path)
            if attach_path.exists():
                with open(attach_path, "rb") as f:
                    file_data = f.read()
                msg.add_attachment(
                    file_data,
                    maintype="application",
                    subtype="octet-stream",
                    filename=attach_path.name,
                )
        
        # Send email
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, context=context
        ) as server:
            server.login(settings.EMAIL_USER, settings.EMAIL_PASSWORD)
            server.send_message(msg)
        
        result = {
            "success": True,
            "to": to_email,
            "subject": subject,
        }
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in send_email task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.misc_tasks.cleanup_old_files",
    queue="misc",
    max_retries=1,
)
def cleanup_old_files(
    self,
    job_id: str,
    directory: str,
    max_age_days: int = 7,
    extensions: Optional[List[str]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Clean up old files from a directory.
    
    Args:
        job_id: Job ID for tracking
        directory: Directory to clean
        max_age_days: Maximum file age in days
        extensions: List of extensions to clean (e.g., ['.pdf', '.tmp'])
    """
    import time
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Cleaning {directory}")
        
        dir_path = Path(directory)
        if not dir_path.exists():
            result = {"success": False, "error": "Directory not found"}
            job_service.fail_job(job_uuid, result["error"])
            return result
        
        cutoff_time = time.time() - (max_age_days * 86400)
        deleted = []
        errors = []
        
        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue
            
            # Check extension filter
            if extensions and file_path.suffix.lower() not in extensions:
                continue
            
            # Check age
            if file_path.stat().st_mtime < cutoff_time:
                try:
                    file_path.unlink()
                    deleted.append(str(file_path))
                except Exception as e:
                    errors.append({"path": str(file_path), "error": str(e)})
        
        result = {
            "success": True,
            "deleted_count": len(deleted),
            "deleted_files": deleted[:100],  # Limit for response size
            "errors": errors[:10],
        }
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in cleanup_old_files task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()


@shared_task(
    bind=True,
    base=BaseTaskWithRetry,
    name="backend.tasks.misc_tasks.export_data",
    queue="misc",
    max_retries=2,
)
def export_data(
    self,
    job_id: str,
    export_type: str,
    export_format: str = "json",
    filters: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Export data to a file.
    
    Args:
        job_id: Job ID for tracking
        export_type: Type of data to export (e.g., 'grading_results', 'quiz_results')
        export_format: Output format ('json', 'csv', 'xlsx')
        filters: Optional filters to apply
    """
    import json
    from datetime import datetime
    
    from backend.core.config import settings
    
    job_service, db_session = get_sync_job_service()
    job_uuid = uuid.UUID(job_id)
    
    try:
        job_service.start_job(job_uuid, f"Exporting {export_type}")
        
        exports_dir = settings.PROJECT_ROOT / "exports"
        exports_dir.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{export_type}_{timestamp}.{export_format}"
        output_path = exports_dir / filename
        
        # Get data based on export type
        job_service.update_progress(job_uuid, 20, "Fetching data")
        
        if export_type == "grading_results":
            from backend.services import grading_service
            data = grading_service.get_all_results(filters or {})
        else:
            data = {"error": f"Unknown export type: {export_type}"}
        
        # Export to format
        job_service.update_progress(job_uuid, 60, f"Writing {export_format.upper()}")
        
        if export_format == "json":
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        elif export_format == "csv":
            import csv
            if isinstance(data, list) and data:
                with open(output_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=data[0].keys())
                    writer.writeheader()
                    writer.writerows(data)
        elif export_format == "xlsx":
            import pandas as pd
            df = pd.DataFrame(data)
            df.to_excel(output_path, index=False)
        
        result = {
            "success": True,
            "export_type": export_type,
            "format": export_format,
            "path": str(output_path),
            "record_count": len(data) if isinstance(data, list) else 1,
        }
        
        job_service.complete_job(job_uuid, result)
        return result
        
    except Exception as e:
        logger.exception(f"Error in export_data task: {e}")
        job_service.fail_job(job_uuid, str(e))
        raise
    finally:
        db_session.close()
