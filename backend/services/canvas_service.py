"""
Canvas LMS Service
Handles Canvas API proxy, file downloads, MD5 deduplication, and QTI import
"""
import hashlib
import logging
import json
import base64
import asyncio
from pathlib import Path
from typing import Optional
import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Directory for storing Canvas downloads with MD5 deduplication
CANVAS_DOWNLOADS_DIR = settings.DATA_DIR / "canvas_downloads"
MD5_REGISTRY_FILE = CANVAS_DOWNLOADS_DIR / ".md5_registry.json"


def ensure_download_dir():
    """Ensure the canvas downloads directory exists"""
    CANVAS_DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def load_md5_registry() -> dict[str, str]:
    """Load MD5 registry from disk"""
    ensure_download_dir()
    if MD5_REGISTRY_FILE.exists():
        try:
            with open(MD5_REGISTRY_FILE, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load MD5 registry: {e}")
    return {}


def save_md5_registry(registry: dict[str, str]):
    """Save MD5 registry to disk"""
    ensure_download_dir()
    try:
        with open(MD5_REGISTRY_FILE, 'w') as f:
            json.dump(registry, f, indent=2)
    except IOError as e:
        logger.error(f"Failed to save MD5 registry: {e}")


def compute_md5(content: bytes) -> str:
    """Compute MD5 hash of content"""
    return hashlib.md5(content).hexdigest()


def check_duplicate(md5_hash: str, registry: dict[str, str]) -> Optional[str]:
    """
    Check if a file with the same MD5 already exists
    Returns the existing filename if duplicate, None otherwise
    """
    for existing_hash, filename in registry.items():
        if existing_hash == md5_hash:
            return filename
    return None


async def fetch_canvas_courses(token: str, base_url: str) -> dict:
    """
    Fetch user's courses from Canvas API
    GET /api/v1/users/self/courses
    """
    url = f"{base_url.rstrip('/')}/api/v1/users/self/courses"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "per_page": 100,
        "include[]": ["term", "total_students"],
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            courses = response.json()
            return {
                "success": True,
                "courses": courses,
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {
                    "success": False,
                    "error": "Invalid or expired access token",
                    "courses": [],
                }
            logger.error(f"Canvas API error: {e}")
            return {
                "success": False,
                "error": f"Canvas API error: {e.response.status_code}",
                "courses": [],
            }
        except httpx.RequestError as e:
            logger.error(f"Network error fetching courses: {e}")
            return {
                "success": False,
                "error": "Network error connecting to Canvas",
                "courses": [],
            }


async def fetch_course_files(token: str, base_url: str, course_id: int) -> dict:
    """
    Fetch files from a Canvas course
    GET /api/v1/courses/{course_id}/files
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/files"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "per_page": 100,
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            files = response.json()
            return {
                "success": True,
                "files": files,
                "course_id": course_id,
            }
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                return {
                    "success": False,
                    "error": "Invalid or expired access token",
                    "files": [],
                    "course_id": course_id,
                }
            if e.response.status_code == 403:
                return {
                    "success": False,
                    "error": "Access denied to this course",
                    "files": [],
                    "course_id": course_id,
                }
            logger.error(f"Canvas API error: {e}")
            return {
                "success": False,
                "error": f"Canvas API error: {e.response.status_code}",
                "files": [],
                "course_id": course_id,
            }
        except httpx.RequestError as e:
            logger.error(f"Network error fetching files: {e}")
            return {
                "success": False,
                "error": "Network error connecting to Canvas",
                "files": [],
                "course_id": course_id,
            }


async def download_file_with_dedup(
    file_id: int,
    filename: str,
    download_url: str,
    course_id: int,
) -> dict:
    """
    Download a file from Canvas with MD5 deduplication
    
    1. Download file content (follow redirects like curl -L)
    2. Compute MD5 hash
    3. Check if duplicate exists
    4. Save only if unique
    
    Returns download status: queued, downloading, hashing, saved, duplicate, failed
    """
    ensure_download_dir()
    registry = load_md5_registry()
    
    # Create course-specific subdirectory
    course_dir = CANVAS_DOWNLOADS_DIR / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        # Download file (follow redirects)
        async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
            response = await client.get(download_url)
            response.raise_for_status()
            content = response.content
        
        # Compute MD5
        md5_hash = compute_md5(content)
        
        # Check for duplicate
        existing = check_duplicate(md5_hash, registry)
        if existing:
            logger.info(f"Duplicate file detected: {filename} (matches {existing})")
            return {
                "success": True,
                "file_id": file_id,
                "filename": filename,
                "status": "duplicate",
                "md5_hash": md5_hash,
                "existing_file": existing,
            }
        
        # Save file
        # Sanitize filename
        safe_filename = "".join(c for c in filename if c.isalnum() or c in "._- ")
        if not safe_filename:
            safe_filename = f"file_{file_id}"
        
        # Ensure unique filename
        file_path = course_dir / safe_filename
        counter = 1
        base_name = file_path.stem
        suffix = file_path.suffix
        while file_path.exists():
            file_path = course_dir / f"{base_name}_{counter}{suffix}"
            counter += 1
        
        with open(file_path, 'wb') as f:
            f.write(content)
        
        # Update registry
        registry[md5_hash] = str(file_path.relative_to(CANVAS_DOWNLOADS_DIR))
        save_md5_registry(registry)
        
        logger.info(f"Saved file: {file_path}")
        return {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "status": "saved",
            "md5_hash": md5_hash,
            "saved_path": str(file_path.relative_to(CANVAS_DOWNLOADS_DIR)),
        }
        
    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error downloading {filename}: {e}")
        return {
            "success": False,
            "file_id": file_id,
            "filename": filename,
            "status": "failed",
            "error": f"HTTP error: {e.response.status_code}",
        }
    except httpx.RequestError as e:
        logger.error(f"Network error downloading {filename}: {e}")
        return {
            "success": False,
            "file_id": file_id,
            "filename": filename,
            "status": "failed",
            "error": "Network error during download",
        }
    except IOError as e:
        logger.error(f"IO error saving {filename}: {e}")
        return {
            "success": False,
            "file_id": file_id,
            "filename": filename,
            "status": "failed",
            "error": "Failed to save file",
        }


async def download_files_batch(
    course_id: int,
    files: list[dict],
) -> dict:
    """
    Download multiple files with MD5 deduplication
    
    files: list of {file_id, filename, url}
    
    Returns summary with per-file results
    """
    results = []
    saved = 0
    duplicates = 0
    failed = 0
    
    for file_info in files:
        result = await download_file_with_dedup(
            file_id=file_info["file_id"],
            filename=file_info["filename"],
            download_url=file_info["url"],
            course_id=course_id,
        )
        results.append(result)
        
        if result["status"] == "saved":
            saved += 1
        elif result["status"] == "duplicate":
            duplicates += 1
        elif result["status"] == "failed":
            failed += 1
    
    return {
        "success": failed == 0,
        "results": results,
        "total": len(files),
        "saved": saved,
        "duplicates": duplicates,
        "failed": failed,
    }


# ============================================================================
# QTI Import via Content Migration
# ============================================================================

async def create_qti_migration(
    token: str,
    base_url: str,
    course_id: int,
    question_bank_name: str,
    filename: str = "qti_import.zip",
) -> dict:
    """
    Create a QTI content migration in Canvas.
    POST /api/v1/courses/{course_id}/content_migrations
    
    Returns migration details including pre_attachment upload info.
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/content_migrations"
    headers = {"Authorization": f"Bearer {token}"}
    
    # Form data for QTI migration
    data = {
        "migration_type": "qti_converter",
        "settings[question_bank_name]": question_bank_name,
        "pre_attachment[name]": filename,
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(url, headers=headers, data=data)
            response.raise_for_status()
            migration = response.json()
            
            logger.info(f"Created content migration {migration.get('id')} for course {course_id}")
            return {
                "success": True,
                "migration": migration,
            }
        except httpx.HTTPStatusError as e:
            error_detail = "Unknown error"
            try:
                error_body = e.response.json()
                error_detail = error_body.get("message", error_body.get("errors", str(e)))
            except Exception:
                error_detail = e.response.text[:200]
            
            logger.error(f"Canvas API error creating migration: {e} - {error_detail}")
            return {
                "success": False,
                "error": f"Canvas API error ({e.response.status_code}): {error_detail}",
            }
        except httpx.RequestError as e:
            logger.error(f"Network error creating migration: {e}")
            return {
                "success": False,
                "error": "Network error connecting to Canvas",
            }


async def upload_to_pre_attachment(
    upload_url: str,
    upload_params: dict,
    file_param: str,
    file_content: bytes,
    filename: str,
) -> dict:
    """
    Upload file to Canvas pre_attachment URL (typically S3).
    Uses multipart/form-data with all params from pre_attachment.
    """
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        try:
            # Build multipart form with upload_params
            files = {file_param: (filename, file_content, "application/zip")}
            data = upload_params.copy()
            
            logger.info(f"Uploading to {upload_url} with params: {list(data.keys())}")
            
            response = await client.post(upload_url, data=data, files=files)
            
            # Canvas S3 upload typically returns 201 or redirects
            if response.status_code in [200, 201, 204, 301, 302, 303]:
                logger.info(f"Upload successful, status: {response.status_code}")
                return {
                    "success": True,
                    "status_code": response.status_code,
                }
            else:
                logger.error(f"Upload failed: {response.status_code} - {response.text[:200]}")
                return {
                    "success": False,
                    "error": f"Upload failed with status {response.status_code}",
                }
        except httpx.RequestError as e:
            logger.error(f"Network error during upload: {e}")
            return {
                "success": False,
                "error": f"Network error during upload: {str(e)}",
            }


async def poll_migration_progress(
    token: str,
    base_url: str,
    course_id: int,
    migration_id: int,
    max_attempts: int = 60,
    poll_interval: float = 2.0,
) -> dict:
    """
    Poll the content migration progress until completed or failed.
    GET /api/v1/courses/{course_id}/content_migrations/{migration_id}
    
    Workflow states: pre_processing, running, completed, failed
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/content_migrations/{migration_id}"
    headers = {"Authorization": f"Bearer {token}"}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(max_attempts):
            try:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                migration = response.json()
                
                workflow_state = migration.get("workflow_state", "unknown")
                progress = migration.get("progress", 0)
                
                logger.info(f"Migration {migration_id} status: {workflow_state} ({progress}%)")
                
                if workflow_state == "completed":
                    return {
                        "success": True,
                        "status": "completed",
                        "migration": migration,
                    }
                elif workflow_state in ["failed", "pre_process_error"]:
                    migration_issues = migration.get("migration_issues", [])
                    error_msg = "Migration failed"
                    if migration_issues:
                        error_msg = migration_issues[0].get("description", error_msg)
                    return {
                        "success": False,
                        "status": "failed",
                        "error": error_msg,
                        "migration": migration,
                    }
                elif workflow_state in ["pre_processing", "running", "queued", "exporting", "importing"]:
                    # Still in progress
                    await asyncio.sleep(poll_interval)
                else:
                    logger.warning(f"Unknown migration state: {workflow_state}")
                    await asyncio.sleep(poll_interval)
                    
            except httpx.HTTPStatusError as e:
                logger.error(f"Error polling migration: {e}")
                return {
                    "success": False,
                    "status": "failed",
                    "error": f"API error polling migration: {e.response.status_code}",
                }
            except httpx.RequestError as e:
                logger.error(f"Network error polling migration: {e}")
                # Continue polling on network errors
                await asyncio.sleep(poll_interval)
        
        return {
            "success": False,
            "status": "timeout",
            "error": "Migration timed out after maximum polling attempts",
        }


async def import_qti_to_canvas(
    token: str,
    base_url: str,
    course_id: int,
    question_bank_name: str,
    qti_zip_content: bytes,
    filename: str = "qti_import.zip",
) -> dict:
    """
    Complete QTI import workflow:
    1. Create content migration (get pre_attachment info)
    2. Upload QTI zip to pre_attachment URL
    3. Poll until migration completes
    
    Returns final status with success/failure.
    """
    # Step 1: Create migration
    logger.info(f"Step 1: Creating QTI migration for course {course_id}, bank: {question_bank_name}")
    migration_result = await create_qti_migration(
        token=token,
        base_url=base_url,
        course_id=course_id,
        question_bank_name=question_bank_name,
        filename=filename,
    )
    
    if not migration_result["success"]:
        return {
            "success": False,
            "status": "failed",
            "error": migration_result.get("error", "Failed to create migration"),
        }
    
    migration = migration_result["migration"]
    migration_id = migration.get("id")
    pre_attachment = migration.get("pre_attachment", {})
    
    # Check if we have upload info
    upload_url = pre_attachment.get("upload_url")
    upload_params = pre_attachment.get("upload_params", {})
    file_param = pre_attachment.get("file_param", "file")
    
    if not upload_url:
        # Some Canvas instances may not require file upload for certain migrations
        # or the migration is already queued
        logger.info("No pre_attachment URL, checking migration progress directly")
    else:
        # Step 2: Upload file
        logger.info(f"Step 2: Uploading QTI zip ({len(qti_zip_content)} bytes) to pre_attachment")
        upload_result = await upload_to_pre_attachment(
            upload_url=upload_url,
            upload_params=upload_params,
            file_param=file_param,
            file_content=qti_zip_content,
            filename=filename,
        )
        
        if not upload_result["success"]:
            return {
                "success": False,
                "status": "failed",
                "error": upload_result.get("error", "Failed to upload QTI file"),
                "migration_id": migration_id,
            }
    
    # Step 3: Poll for completion
    logger.info(f"Step 3: Polling migration {migration_id} for completion")
    poll_result = await poll_migration_progress(
        token=token,
        base_url=base_url,
        course_id=course_id,
        migration_id=migration_id,
    )
    
    if poll_result["success"]:
        return {
            "success": True,
            "status": "completed",
            "migration_id": migration_id,
            "question_bank_name": question_bank_name,
            "message": f"Question bank '{question_bank_name}' imported successfully!",
        }
    else:
        return {
            "success": False,
            "status": poll_result.get("status", "failed"),
            "error": poll_result.get("error", "Migration failed"),
            "migration_id": migration_id,
        }
