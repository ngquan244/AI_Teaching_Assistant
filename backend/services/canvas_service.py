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

from backend.core.config import settings
from backend.core.logger import canvas_logger as logger

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
            logger.debug(f"Duplicate file detected: {filename} (matches {existing})")
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
        
        logger.debug(f"Saved file: {file_path}")
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
            
            logger.debug(f"Created content migration {migration.get('id')} for course {course_id}")
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
    
    IMPORTANT: Do NOT follow redirects - we need to capture the redirect URL
    for the finalization step.
    """
    # Do NOT follow redirects - we need to handle success_action_redirect manually
    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
        try:
            # Build multipart form with upload_params EXACTLY as provided
            files = {file_param: (filename, file_content, "application/zip")}
            data = upload_params.copy()
            
            logger.debug(f"S3 Upload: POST to {upload_url}")
            logger.debug(f"S3 Upload params: {list(data.keys())}")
            
            # Do NOT include Authorization header for S3 upload
            # Do NOT manually set Content-Type (let httpx handle multipart boundary)
            response = await client.post(upload_url, data=data, files=files)
            
            logger.debug(f"S3 Upload response: status={response.status_code}")
            
            # S3 returns 201 (created) or 204 (no content) on success
            # Or 303 (redirect) if success_action_redirect is set
            if response.status_code in [201, 204]:
                logger.debug("S3 Upload successful (direct success)")
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "location": response.headers.get("Location"),
                }
            elif response.status_code in [301, 302, 303, 307, 308]:
                # Redirect response - capture the Location header
                redirect_url = response.headers.get("Location")
                logger.debug(f"S3 Upload returned redirect: {redirect_url}")
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "redirect_url": redirect_url,
                }
            elif response.status_code == 200:
                # Some S3 configs return 200 - check for redirect in body or headers
                logger.warning("S3 Upload returned 200 - may need finalization check")
                return {
                    "success": True,
                    "status_code": response.status_code,
                    "location": response.headers.get("Location"),
                }
            else:
                error_text = response.text[:500] if response.text else "No response body"
                logger.error(f"S3 Upload failed: {response.status_code} - {error_text}")
                return {
                    "success": False,
                    "error": f"S3 upload failed with status {response.status_code}: {error_text}",
                }
        except httpx.RequestError as e:
            logger.error(f"Network error during S3 upload: {e}")
            return {
                "success": False,
                "error": f"Network error during S3 upload: {str(e)}",
            }


async def finalize_file_upload(
    token: str,
    finalize_url: str,
) -> dict:
    """
    Finalize file upload by calling the success_action_redirect URL.
    
    This step is REQUIRED after S3 upload to tell Canvas the file is ready.
    Without this, Canvas shows "file not available" and migration stays in pre_processing.
    """
    logger.debug(f"Finalize: GET {finalize_url}")
    
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        try:
            # This request MUST include Authorization header
            headers = {"Authorization": f"Bearer {token}"}
            response = await client.get(finalize_url, headers=headers)
            
            logger.debug(f"Finalize response: status={response.status_code}")
            
            if response.status_code in [200, 201, 301, 302, 303]:
                # Try to parse response for file confirmation
                try:
                    file_info = response.json()
                    logger.debug(f"Finalize success: file_id={file_info.get('id')}, size={file_info.get('size')}")
                    return {
                        "success": True,
                        "file_info": file_info,
                    }
                except Exception:
                    # Response may not be JSON, but that's OK
                    logger.debug("Finalize completed (non-JSON response)")
                    return {
                        "success": True,
                    }
            else:
                error_text = response.text[:500] if response.text else "No response body"
                logger.error(f"Finalize failed: {response.status_code} - {error_text}")
                return {
                    "success": False,
                    "error": f"Finalize failed with status {response.status_code}",
                }
        except httpx.RequestError as e:
            logger.error(f"Network error during finalize: {e}")
            return {
                "success": False,
                "error": f"Network error during finalize: {str(e)}",
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
                
                logger.debug(f"Migration {migration_id} poll #{attempt+1}: state={workflow_state}, progress={progress}%")
                
                if workflow_state == "completed":
                    return {
                        "success": True,
                        "status": "completed",
                        "migration": migration,
                    }
                elif workflow_state in ["failed", "pre_process_error"]:
                    # Fetch migration issues for detailed error
                    error_msg = "Migration failed"
                    migration_issues_url = migration.get("migration_issues_url")
                    
                    if migration_issues_url:
                        try:
                            issues_response = await client.get(migration_issues_url, headers=headers)
                            if issues_response.status_code == 200:
                                issues = issues_response.json()
                                if issues and len(issues) > 0:
                                    error_msg = issues[0].get("description", error_msg)
                                    logger.error(f"Migration issues: {issues}")
                        except Exception as e:
                            logger.warning(f"Could not fetch migration issues: {e}")
                    
                    # Also check inline migration_issues
                    inline_issues = migration.get("migration_issues", [])
                    if inline_issues and len(inline_issues) > 0:
                        error_msg = inline_issues[0].get("description", error_msg)
                    
                    logger.error(f"Migration {migration_id} failed: {error_msg}")
                    return {
                        "success": False,
                        "status": "failed",
                        "error": error_msg,
                        "migration": migration,
                    }
                elif workflow_state in ["pre_processing", "running", "queued", "exporting", "importing"]:
                    # Still in progress - check if stuck in pre_processing too long
                    if workflow_state == "pre_processing" and attempt > 10:
                        logger.warning(f"Migration stuck in pre_processing for {attempt * poll_interval}s - file may not be attached")
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
            "error": "Migration timed out after maximum polling attempts. Check Canvas for status.",
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
    2. Upload QTI zip to S3 (pre_attachment URL)
    3. FINALIZE file attachment (call success_action_redirect)
    4. Poll until migration completes
    
    Returns final status with success/failure.
    """
    # Step 1: Create migration
    logger.info(f"QTI import starting: course={course_id}, bank={question_bank_name}")
    migration_result = await create_qti_migration(
        token=token,
        base_url=base_url,
        course_id=course_id,
        question_bank_name=question_bank_name,
        filename=filename,
    )
    
    if not migration_result["success"]:
        logger.error(f"Step 1 FAILED: {migration_result.get('error')}")
        return {
            "success": False,
            "status": "failed",
            "error": migration_result.get("error", "Failed to create migration"),
        }
    
    migration = migration_result["migration"]
    migration_id = migration.get("id")
    pre_attachment = migration.get("pre_attachment", {})
    progress_url = migration.get("progress_url")
    
    logger.debug(f"Step 1 OK: migration_id={migration_id}")
    
    # Extract upload info
    upload_url = pre_attachment.get("upload_url")
    upload_params = pre_attachment.get("upload_params", {})
    file_param = pre_attachment.get("file_param", "file")
    
    # Get success_action_redirect from upload_params (this is the finalize URL)
    success_redirect = upload_params.get("success_action_redirect")
    
    logger.debug(f"pre_attachment: url={upload_url}, file_param={file_param}, redirect={success_redirect}")
    
    if not upload_url:
        logger.warning("No pre_attachment URL provided - migration may already be queued")
    else:
        # Step 2: Upload file to S3
        logger.debug(f"Step 2: Uploading QTI zip ({len(qti_zip_content)} bytes) to S3")
        upload_result = await upload_to_pre_attachment(
            upload_url=upload_url,
            upload_params=upload_params,
            file_param=file_param,
            file_content=qti_zip_content,
            filename=filename,
        )
        
        if not upload_result["success"]:
            logger.error(f"Step 2 FAILED: {upload_result.get('error')}")
            return {
                "success": False,
                "status": "failed",
                "error": upload_result.get("error", "Failed to upload QTI file to S3"),
                "migration_id": migration_id,
            }
        
        logger.debug(f"Step 2 OK: status_code={upload_result.get('status_code')}")
        
        # Step 3: FINALIZE file attachment (CRITICAL STEP)
        # Determine finalize URL: use redirect from S3 response, or success_action_redirect
        finalize_url = upload_result.get("redirect_url") or upload_result.get("location") or success_redirect
        
        if finalize_url:
            logger.debug(f"Step 3: Finalizing file attachment")
            finalize_result = await finalize_file_upload(
                token=token,
                finalize_url=finalize_url,
            )
            
            if not finalize_result["success"]:
                logger.error(f"Step 3 FAILED: {finalize_result.get('error')}")
                return {
                    "success": False,
                    "status": "failed",
                    "error": finalize_result.get("error", "Failed to finalize file upload"),
                    "migration_id": migration_id,
                }
            
            logger.debug(f"Step 3 OK: File finalized")
        else:
            logger.warning("Step 3 SKIPPED: No finalize URL available (may cause 'file not available' error)")
    
    # Step 4: Poll for completion
    logger.debug(f"Step 4: Polling migration {migration_id}")
    poll_result = await poll_migration_progress(
        token=token,
        base_url=base_url,
        course_id=course_id,
        migration_id=migration_id,
    )
    
    if poll_result["success"]:
        logger.info(f"QTI import succeeded: migration_id={migration_id}, bank={question_bank_name}")
        return {
            "success": True,
            "status": "completed",
            "migration_id": migration_id,
            "question_bank_name": question_bank_name,
            "message": f"Question bank '{question_bank_name}' imported successfully!",
        }
    else:
        logger.error(f"=== QTI IMPORT FAILED: {poll_result.get('error')} ===")
        return {
            "success": False,
            "status": poll_result.get("status", "failed"),
            "error": poll_result.get("error", "Migration failed"),
            "migration_id": migration_id,
        }


# ============================================================================
# Canvas Quiz API — Quizzes, Questions, Groups
# ============================================================================

async def list_quiz_questions(
    token: str, base_url: str, course_id: int, quiz_id: int
) -> dict:
    """
    List all questions in an existing quiz.
    GET /api/v1/courses/{course_id}/quizzes/{quiz_id}/questions
    
    This is the primary way to discover available questions on the UET Canvas
    instance (the Assessment Question Banks API is not available).
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        f"/quizzes/{quiz_id}/questions"
    )
    headers = {"Authorization": f"Bearer {token}"}
    
    all_questions = []
    page = 1
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            while True:
                response = await client.get(
                    url, headers=headers, params={"per_page": 50, "page": page}
                )
                response.raise_for_status()
                questions = response.json()
                if not questions:
                    break
                all_questions.extend(questions)
                link = response.headers.get("Link", "")
                if 'rel="next"' not in link:
                    break
                page += 1
            
            return {
                "success": True,
                "questions": all_questions,
                "quiz_id": quiz_id,
                "total": len(all_questions),
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"Canvas API error listing quiz questions: {e}")
            return {
                "success": False,
                "error": f"Canvas API error: {e.response.status_code}",
                "questions": [],
                "quiz_id": quiz_id,
            }
        except httpx.RequestError as e:
            logger.error(f"Network error listing quiz questions: {e}")
            return {
                "success": False,
                "error": "Network error connecting to Canvas",
                "questions": [],
                "quiz_id": quiz_id,
            }


async def list_quizzes(token: str, base_url: str, course_id: int) -> dict:
    """
    List quizzes for a course.
    GET /api/v1/courses/{course_id}/quizzes
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/quizzes"
    headers = {"Authorization": f"Bearer {token}"}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                url, headers=headers, params={"per_page": 50}
            )
            response.raise_for_status()
            quizzes = response.json()
            return {"success": True, "quizzes": quizzes, "course_id": course_id}
        except httpx.HTTPStatusError as e:
            logger.error(f"Canvas API error listing quizzes: {e}")
            return {
                "success": False,
                "error": f"Canvas API error: {e.response.status_code}",
                "quizzes": [],
            }
        except httpx.RequestError as e:
            logger.error(f"Network error listing quizzes: {e}")
            return {
                "success": False,
                "error": "Network error connecting to Canvas",
                "quizzes": [],
            }


async def create_quiz(
    token: str, base_url: str, course_id: int, quiz_params: dict
) -> dict:
    """
    Create a new quiz for a course.
    POST /api/v1/courses/{course_id}/quizzes
    
    quiz_params keys: title, description, quiz_type, time_limit,
                      shuffle_answers, allowed_attempts, published
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/quizzes"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    # Wrap under quiz[] namespace as Canvas expects
    payload = {"quiz": quiz_params}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            quiz = response.json()
            return {
                "success": True,
                "quiz": quiz,
                "quiz_id": quiz.get("id"),
                "html_url": quiz.get("html_url"),
            }
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error(f"Canvas API error creating quiz: {e} — {body}")
            return {
                "success": False,
                "error": f"Canvas API error {e.response.status_code}: {body}",
            }
        except httpx.RequestError as e:
            logger.error(f"Network error creating quiz: {e}")
            return {"success": False, "error": "Network error connecting to Canvas"}


async def add_quiz_question(
    token: str,
    base_url: str,
    course_id: int,
    quiz_id: int,
    question_data: dict,
) -> dict:
    """
    Add a single question to a quiz.
    POST /api/v1/courses/{course_id}/quizzes/{quiz_id}/questions
    
    question_data should follow Canvas Quiz Question format:
      question_name, question_text, question_type, points_possible, answers[]
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        f"/quizzes/{quiz_id}/questions"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"question": question_data}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            q = response.json()
            return {"success": True, "question": q, "question_id": q.get("id")}
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error(f"Error adding quiz question: {e} — {body}")
            return {"success": False, "error": f"Canvas API error: {body}"}
        except httpx.RequestError as e:
            logger.error(f"Network error adding quiz question: {e}")
            return {"success": False, "error": "Network error"}


async def create_question_group(
    token: str,
    base_url: str,
    course_id: int,
    quiz_id: int,
    group_name: str,
    pick_count: int,
    question_points: float,
    bank_id: int,
) -> dict:
    """
    Create a question group linked to an assessment question bank.
    POST /api/v1/courses/{course_id}/quizzes/{quiz_id}/groups
    
    This makes Canvas randomly pick `pick_count` questions from the bank.
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        f"/quizzes/{quiz_id}/groups"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "quiz_groups": [
            {
                "name": group_name,
                "pick_count": pick_count,
                "question_points": question_points,
                "assessment_question_bank_id": bank_id,
            }
        ]
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            groups = response.json()
            return {"success": True, "groups": groups}
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error(f"Error creating question group: {e} — {body}")
            return {"success": False, "error": f"Canvas API error: {body}"}
        except httpx.RequestError as e:
            logger.error(f"Network error creating group: {e}")
            return {"success": False, "error": "Network error"}


async def publish_quiz(
    token: str, base_url: str, course_id: int, quiz_id: int
) -> dict:
    """
    Publish a quiz.
    PUT /api/v1/courses/{course_id}/quizzes/{quiz_id}
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/quizzes/{quiz_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"quiz": {"published": True}}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.put(url, headers=headers, json=payload)
            response.raise_for_status()
            quiz = response.json()
            return {"success": True, "quiz": quiz}
        except httpx.HTTPStatusError as e:
            body = e.response.text
            logger.error(f"Error publishing quiz: {e} — {body}")
            return {"success": False, "error": f"Canvas API error: {body}"}
        except httpx.RequestError as e:
            logger.error(f"Network error publishing quiz: {e}")
            return {"success": False, "error": "Network error"}


async def build_full_quiz(
    token: str,
    base_url: str,
    course_id: int,
    quiz_params: dict,
    direct_questions: list | None = None,
    source_questions: list | None = None,
    default_points: float = 1.0,
) -> dict:
    """
    End-to-end quiz builder:
    1. Create the quiz shell
    2. Add *direct* questions (provided inline by the client)
    3. Copy questions from source quizzes (if any)
    4. Optionally publish

    direct_questions format (from AI generation):
      [{"question_text": "...", "options": {"A": "...", ...},
        "correct_keys": ["A"], "points": 1.0,
        "question_type": "multiple_choice_question"}, ...]

    source_questions format (copy from Canvas quiz):
      [{"source_quiz_id": 123, "question_ids": [456, 789]}, ...]

    Returns summary with quiz_id, quiz_url, counts.
    """
    direct_questions = direct_questions or []
    source_questions = source_questions or []

    should_publish = quiz_params.pop("published", False)
    quiz_params["published"] = False  # create unpublished first

    # --- Step 1: Create quiz ---
    logger.info(f"Creating quiz '{quiz_params.get('title')}' in course {course_id}")
    create_result = await create_quiz(token, base_url, course_id, quiz_params)
    if not create_result["success"]:
        return create_result

    quiz_id = create_result["quiz_id"]
    quiz_url = create_result.get("html_url", "")
    questions_added = 0

    # --- Step 2: Add direct questions ---
    for idx, dq in enumerate(direct_questions):
        options = dq.get("options", {})
        correct_keys = set(dq.get("correct_keys", []))
        q_type = dq.get("question_type", "multiple_choice_question")

        # If multiple correct keys, switch to multiple_answers_question
        if len(correct_keys) > 1:
            q_type = "multiple_answers_question"

        answers = []
        for letter, text in sorted(options.items()):
            answers.append({
                "answer_text": text,
                "answer_weight": 100 if letter in correct_keys else 0,
            })

        question_payload = {
            "question_name": f"Question {idx + 1}",
            "question_text": dq.get("question_text", ""),
            "question_type": q_type,
            "points_possible": dq.get("points", default_points),
            "answers": answers,
        }

        add_result = await add_quiz_question(
            token, base_url, course_id, quiz_id, question_payload
        )
        if add_result["success"]:
            questions_added += 1
        else:
            logger.warning(f"Failed to add direct question {idx}: {add_result.get('error')}")

    # --- Step 3: Copy questions from source quizzes ---
    for selection in source_questions:
        src_quiz_id = selection["source_quiz_id"]
        q_ids = set(selection["question_ids"])
        
        # Fetch questions from the source quiz
        src_result = await list_quiz_questions(token, base_url, course_id, src_quiz_id)
        if not src_result["success"]:
            logger.warning(
                f"Failed to list questions from quiz {src_quiz_id}: "
                f"{src_result.get('error')}"
            )
            continue
        
        for q_data in src_result["questions"]:
            if q_data["id"] not in q_ids:
                continue
            
            # Re-create the question in the new quiz
            question_payload = {
                "question_name": q_data.get("question_name", f"Question {q_data['id']}"),
                "question_text": q_data.get("question_text", ""),
                "question_type": q_data.get("question_type", "multiple_choice_question"),
                "points_possible": q_data.get("points_possible", default_points),
                "answers": q_data.get("answers", []),
            }
            # Include optional fields if present
            for field in ("correct_comments", "incorrect_comments", "neutral_comments",
                          "correct_comments_html", "incorrect_comments_html", "neutral_comments_html",
                          "matches", "matching_answer_incorrect_matches", "variables",
                          "formulas", "formula_decimal_places", "answer_tolerance"):
                if q_data.get(field):
                    question_payload[field] = q_data[field]
            
            add_result = await add_quiz_question(
                token, base_url, course_id, quiz_id, question_payload
            )
            if add_result["success"]:
                questions_added += 1
            else:
                logger.warning(f"Failed to add question {q_data['id']}: {add_result.get('error')}")
    
    # --- Step 4: Publish if requested ---
    if should_publish:
        pub_result = await publish_quiz(token, base_url, course_id, quiz_id)
        if not pub_result["success"]:
            logger.warning(f"Quiz created but publish failed: {pub_result.get('error')}")
    
    return {
        "success": True,
        "quiz_id": quiz_id,
        "quiz_url": quiz_url,
        "title": quiz_params.get("title", ""),
        "questions_added": questions_added,
        "published": should_publish,
        "message": f"Quiz created with {questions_added} questions.",
    }


# ============================================================================
# Canvas Assessment Question Banks
# ============================================================================

async def list_question_banks(token: str, base_url: str, course_id: int) -> dict:
    """
    List assessment question banks for a course.
    GET /api/v1/courses/{course_id}/question_banks
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/question_banks"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                url, headers=headers, params={"per_page": 50}
            )
            response.raise_for_status()
            banks = response.json()
            return {"success": True, "banks": banks}
        except httpx.HTTPStatusError as e:
            logger.error(f"Canvas API error listing question banks: {e}")
            return {
                "success": False,
                "error": f"Canvas API error: {e.response.status_code}",
                "banks": [],
            }
        except httpx.RequestError as e:
            logger.error(f"Network error listing question banks: {e}")
            return {
                "success": False,
                "error": "Network error connecting to Canvas",
                "banks": [],
            }


async def list_bank_questions(
    token: str, base_url: str, course_id: int, bank_id: int
) -> dict:
    """
    List questions in an assessment question bank.
    GET /api/v1/courses/{course_id}/question_banks/{bank_id}/questions
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        f"/question_banks/{bank_id}/questions"
    )
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(
                url, headers=headers, params={"per_page": 50}
            )
            response.raise_for_status()
            questions = response.json()
            return {"success": True, "questions": questions}
        except httpx.HTTPStatusError as e:
            logger.error(f"Canvas API error listing bank questions: {e}")
            return {
                "success": False,
                "error": f"Canvas API error: {e.response.status_code}",
                "questions": [],
            }
        except httpx.RequestError as e:
            logger.error(f"Network error listing bank questions: {e}")
            return {
                "success": False,
                "error": "Network error connecting to Canvas",
                "questions": [],
            }


# ============================================================================
# Canvas User, Enrollment, Quiz-Submission APIs  (Simulation + Results)
# ============================================================================

def _masq(params: dict | None, as_user_id: int | None) -> dict:
    """Inject ``as_user_id`` query-param when masquerading."""
    params = dict(params or {})
    if as_user_id is not None:
        params["as_user_id"] = as_user_id
    return params


def _parse_canvas_user_error(response: httpx.Response) -> str | None:
    """Extract user-friendly message from Canvas user-creation error."""
    try:
        data = response.json()
        errors = data.get("errors", {})
        msgs = []
        # pseudonym unique_id taken
        uid_errors = errors.get("pseudonym", {}).get("unique_id", [])
        for e in uid_errors:
            if e.get("type") == "taken":
                msgs.append("Email/login ID đã tồn tại trên Canvas. Hãy dùng email khác.")
        # generic pseudonym invalid
        pseudo_errors = errors.get("user", {}).get("pseudonyms", [])
        for e in pseudo_errors:
            if e.get("type") == "invalid":
                msgs.append("Pseudonym không hợp lệ.")
        if msgs:
            return " | ".join(msgs)
    except Exception:
        pass
    return None


async def create_canvas_user(
    token: str,
    base_url: str,
    account_id: str | int,
    name: str,
    email: str,
    *,
    skip_registration: bool = True,
) -> dict:
    """
    Create a new user in a Canvas account.
    POST /api/v1/accounts/:account_id/users
    """
    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/users"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    payload = {
        "user": {"name": name, "skip_registration": skip_registration},
        "pseudonym": {
            "unique_id": email,
            "send_confirmation": False,
        },
        "communication_channel": {
            "type": "email",
            "address": email,
            "skip_confirmation": True,
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            user = resp.json()
            return {"success": True, "user": user, "canvas_user_id": user["id"]}
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            logger.error(f"Error creating Canvas user: {e} — {body}")
            # Parse common Canvas errors for user-friendly messages
            friendly = _parse_canvas_user_error(e.response)
            return {"success": False, "error": friendly or f"Canvas API {e.response.status_code}: {body}"}
        except httpx.RequestError as e:
            logger.error(f"Network error creating Canvas user: {e}")
            return {"success": False, "error": "Network error"}


async def enroll_user(
    token: str,
    base_url: str,
    course_id: int,
    canvas_user_id: int,
    role: str = "StudentEnrollment",
    state: str = "active",
) -> dict:
    """
    Enroll a Canvas user in a course.
    POST /api/v1/courses/:course_id/enrollments
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/enrollments"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "enrollment": {
            "user_id": canvas_user_id,
            "type": role,
            "enrollment_state": state,
            "notify": False,
        }
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            enrollment = resp.json()
            return {
                "success": True,
                "enrollment": enrollment,
                "enrollment_id": enrollment.get("id"),
            }
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            logger.error(f"Error enrolling user: {e} — {body}")
            return {"success": False, "error": f"Canvas API {e.response.status_code}: {body}"}
        except httpx.RequestError as e:
            logger.error(f"Network error enrolling user: {e}")
            return {"success": False, "error": "Network error"}


async def unenroll_user(
    token: str,
    base_url: str,
    course_id: int,
    enrollment_id: int,
    task: str = "delete",
) -> dict:
    """
    Conclude / deactivate / delete an enrollment.
    DELETE /api/v1/courses/:course_id/enrollments/:id
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/enrollments/{enrollment_id}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"task": task}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.delete(url, headers=headers, params=params)
            resp.raise_for_status()
            return {"success": True, "enrollment": resp.json()}
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            return {"success": False, "error": f"Canvas API {e.response.status_code}: {body}"}
        except httpx.RequestError as e:
            return {"success": False, "error": "Network error"}


async def delete_canvas_user(
    token: str,
    base_url: str,
    account_id: str | int,
    canvas_user_id: int,
) -> dict:
    """
    Delete a user from a Canvas account.
    DELETE /api/v1/accounts/:account_id/users/:user_id
    Requires admin privileges on the account.
    """
    url = f"{base_url.rstrip('/')}/api/v1/accounts/{account_id}/users/{canvas_user_id}"
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.delete(url, headers=headers)
            resp.raise_for_status()
            return {"success": True, "user": resp.json()}
        except httpx.HTTPStatusError as e:
            body = e.response.text[:500]
            logger.error(f"Error deleting Canvas user {canvas_user_id}: {e} — {body}")
            return {"success": False, "error": f"Canvas API {e.response.status_code}: {body}"}
        except httpx.RequestError as e:
            logger.error(f"Network error deleting Canvas user: {e}")
            return {"success": False, "error": "Network error"}


async def get_course_enrollments(
    token: str,
    base_url: str,
    course_id: int,
    *,
    enrollment_type: str | None = "StudentEnrollment",
    per_page: int = 100,
) -> dict:
    """
    List enrollments for a course. Supports pagination.
    GET /api/v1/courses/:course_id/enrollments
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/enrollments"
    headers = {"Authorization": f"Bearer {token}"}
    params: dict = {"per_page": per_page}
    if enrollment_type:
        params["type[]"] = enrollment_type

    all_enrollments: list = []
    page = 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            while True:
                params["page"] = page
                resp = await client.get(url, headers=headers, params=params)
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                all_enrollments.extend(batch)
                if 'rel="next"' not in resp.headers.get("Link", ""):
                    break
                page += 1
            return {"success": True, "enrollments": all_enrollments}
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"Canvas API {e.response.status_code}", "enrollments": []}
        except httpx.RequestError as e:
            return {"success": False, "error": "Network error", "enrollments": []}


# ── Quiz Submission lifecycle ────────────────────────────────────────────

async def start_quiz_submission(
    token: str,
    base_url: str,
    course_id: int,
    quiz_id: int,
    *,
    as_user_id: int | None = None,
    access_code: str | None = None,
) -> dict:
    """
    Start a quiz-taking session (create a QuizSubmission).
    POST /api/v1/courses/:course_id/quizzes/:quiz_id/submissions
    """
    url = f"{base_url.rstrip('/')}/api/v1/courses/{course_id}/quizzes/{quiz_id}/submissions"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body: dict = {}
    if access_code:
        body["access_code"] = access_code

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                url, headers=headers, json=body, params=_masq(None, as_user_id)
            )
            resp.raise_for_status()
            data = resp.json()
            qs = data["quiz_submissions"][0]
            return {
                "success": True,
                "quiz_submission": qs,
                "quiz_submission_id": qs["id"],
                "validation_token": qs["validation_token"],
                "attempt": qs["attempt"],
            }
        except httpx.HTTPStatusError as e:
            body_text = e.response.text[:500]
            logger.error(f"Error starting quiz submission: {e} — {body_text}")
            return {"success": False, "error": f"Canvas API {e.response.status_code}: {body_text}"}
        except httpx.RequestError as e:
            logger.error(f"Network error starting quiz submission: {e}")
            return {"success": False, "error": "Network error"}


async def answer_quiz_questions(
    token: str,
    base_url: str,
    quiz_submission_id: int,
    attempt: int,
    validation_token: str,
    answers: list[dict],
    *,
    as_user_id: int | None = None,
    access_code: str | None = None,
) -> dict:
    """
    Answer one or more quiz questions.
    POST /api/v1/quiz_submissions/:quiz_submission_id/questions

    answers: [{"id": question_id, "answer": <value>}, ...]
    """
    url = f"{base_url.rstrip('/')}/api/v1/quiz_submissions/{quiz_submission_id}/questions"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body: dict = {
        "attempt": attempt,
        "validation_token": validation_token,
        "quiz_questions": answers,
    }
    if access_code:
        body["access_code"] = access_code

    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                url, headers=headers, json=body, params=_masq(None, as_user_id)
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "success": True,
                "quiz_submission_questions": data.get("quiz_submission_questions", []),
            }
        except httpx.HTTPStatusError as e:
            body_text = e.response.text[:500]
            logger.error(f"Error answering quiz questions: {e} — {body_text}")
            return {"success": False, "error": f"Canvas API {e.response.status_code}: {body_text}"}
        except httpx.RequestError as e:
            logger.error(f"Network error answering questions: {e}")
            return {"success": False, "error": "Network error"}


async def complete_quiz_submission(
    token: str,
    base_url: str,
    course_id: int,
    quiz_id: int,
    submission_id: int,
    attempt: int,
    validation_token: str,
    *,
    as_user_id: int | None = None,
    access_code: str | None = None,
) -> dict:
    """
    Complete (turn in) a quiz submission — triggers auto-grading.
    POST /api/v1/courses/:cid/quizzes/:qid/submissions/:sid/complete
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        f"/quizzes/{quiz_id}/submissions/{submission_id}/complete"
    )
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body: dict = {"attempt": attempt, "validation_token": validation_token}
    if access_code:
        body["access_code"] = access_code

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                url, headers=headers, json=body, params=_masq(None, as_user_id)
            )
            resp.raise_for_status()
            data = resp.json()
            qs = data["quiz_submissions"][0]
            return {
                "success": True,
                "quiz_submission": qs,
                "score": qs.get("score"),
                "kept_score": qs.get("kept_score"),
                "workflow_state": qs.get("workflow_state"),
            }
        except httpx.HTTPStatusError as e:
            body_text = e.response.text[:500]
            logger.error(f"Error completing quiz submission: {e} — {body_text}")
            return {"success": False, "error": f"Canvas API {e.response.status_code}: {body_text}"}
        except httpx.RequestError as e:
            logger.error(f"Network error completing submission: {e}")
            return {"success": False, "error": "Network error"}


async def get_quiz_submissions(
    token: str,
    base_url: str,
    course_id: int,
    quiz_id: int,
    *,
    per_page: int = 50,
) -> dict:
    """
    Get all quiz submissions for a quiz.
    GET /api/v1/courses/:course_id/quizzes/:quiz_id/submissions
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        f"/quizzes/{quiz_id}/submissions"
    )
    headers = {"Authorization": f"Bearer {token}"}

    all_subs: list = []
    page = 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            while True:
                resp = await client.get(
                    url, headers=headers, params={"per_page": per_page, "page": page}
                )
                resp.raise_for_status()
                data = resp.json()
                subs = data.get("quiz_submissions", [])
                if not subs:
                    break
                all_subs.extend(subs)
                if 'rel="next"' not in resp.headers.get("Link", ""):
                    break
                page += 1
            return {"success": True, "quiz_submissions": all_subs, "total": len(all_subs)}
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"Canvas API {e.response.status_code}", "quiz_submissions": []}
        except httpx.RequestError as e:
            return {"success": False, "error": "Network error", "quiz_submissions": []}


async def get_assignment_submissions(
    token: str,
    base_url: str,
    course_id: int,
    assignment_id: int,
    *,
    per_page: int = 50,
) -> dict:
    """
    List assignment submissions (quiz submissions link to assignments).
    GET /api/v1/courses/:course_id/assignments/:assignment_id/submissions
    """
    url = (
        f"{base_url.rstrip('/')}/api/v1/courses/{course_id}"
        f"/assignments/{assignment_id}/submissions"
    )
    headers = {"Authorization": f"Bearer {token}"}

    all_subs: list = []
    page = 1

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            while True:
                resp = await client.get(
                    url, headers=headers, params={"per_page": per_page, "page": page}
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                all_subs.extend(batch)
                if 'rel="next"' not in resp.headers.get("Link", ""):
                    break
                page += 1
            return {"success": True, "submissions": all_subs, "total": len(all_subs)}
        except httpx.HTTPStatusError as e:
            return {"success": False, "error": f"Canvas API {e.response.status_code}", "submissions": []}
        except httpx.RequestError as e:
            return {"success": False, "error": "Network error", "submissions": []}
