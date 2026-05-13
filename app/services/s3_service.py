"""AWS S3 service for cloud storage operations."""
import boto3
from botocore.exceptions import ClientError
from PIL import Image, ImageCms
import io
import json
import os
import hashlib
import random
import shutil
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from app.utils.logging_utils import log_service_info as _log_info, log_service_warning as _log_warning, log_service_error as _log_error
from app.utils.user_context import (
    get_user_s3_images_prefix,
    get_user_s3_sku_prefix,
    get_user_s3_csv_prefix,
    get_user_s3_exports_prefix,
    get_user_s3_config_prefix,
    get_user_exports_dir,
    get_user_images_dir,
)


def _get_config(key, default=None):
    """
    Retrieve a configuration value from Flask or environment variables.

    Attempts to get the value from Flask's current_app config first,
    falling back to environment variables if not in Flask context.

    Args:
        key (str): The configuration key to look up.
        default: Default value if key is not found.

    Returns:
        The configuration value or default.
    """
    try:
        from flask import current_app  # Deferred: requires Flask app context (falls back to os.environ outside context)
        return current_app.config.get(key, default)
    except RuntimeError:
        # Not in Flask context, use environment variables
        # Special handling for S3_BUCKET which can also be S3_BUCKET_NAME
        if key == 'S3_BUCKET':
            return os.environ.get('S3_BUCKET_NAME') or os.environ.get('S3_BUCKET', default)
        return os.environ.get(key, default)


def _get_images_prefix():
    """
    Return the S3 prefix for product images based on the configured S3_FOLDER.

    Returns:
        str: e.g. 'production/images/' (always ends with '/')
    """
    s3_folder = _get_config('S3_FOLDER', 'production')
    return f'{s3_folder}/images/'



class S3Service:
    """
    AWS S3 storage service for images and application state.

    Manages all interactions with S3 including image uploads, thumbnail
    generation, file deletion, and persistence of application state
    (SKU counter and CSV inventory) for durability across deployments.
    Includes automatic retry logic with exponential backoff.
    """

    def __init__(self):
        """Initialize the S3Service with lazy-loaded boto3 client."""
        self._client = None

    def _retry_operation(self, operation, *args, max_retries=5, initial_delay=1, **kwargs):
        """
        Execute an S3 operation with automatic retries and exponential backoff.

        On failure, waits with exponential backoff plus random jitter before
        retrying. This handles transient S3 API errors gracefully.

        Args:
            operation (callable): The boto3 client method to execute.
            *args: Positional arguments to pass to the operation.
            max_retries (int): Maximum number of retry attempts. Defaults to 5.
            initial_delay (int): Initial delay in seconds. Defaults to 1.
            **kwargs: Keyword arguments to pass to the operation.

        Returns:
            Any: The result from the operation if successful.

        Raises:
            Exception: If all retry attempts fail.
        """
        retries = 0
        while retries < max_retries:
            try:
                return operation(*args, **kwargs)
            except FileNotFoundError as e:
                # Don't retry if the file doesn't exist (likely a temp file that was cleaned up)
                _log_warning(f"File not found, skipping retry: {e}")
                raise  # Re-raise immediately, don't retry
            except Exception as e:
                retries += 1
                if retries == max_retries:
                    _log_error(f"Operation failed after {max_retries} attempts: {e}")
                    raise
                
                # Exponential backoff: 1s, 2s, 4s, 8s, 16s + random jitter
                delay = initial_delay * (2 ** (retries - 1)) + random.uniform(0, 1)
                _log_warning(f"S3 operation failed: {e}. Retrying in {delay:.2f}s (Attempt {retries}/{max_retries})...")
                time.sleep(delay)
        return None

    def _calculate_md5(self, file_path):
        """
        Calculate the MD5 hash of a file for integrity verification.

        Used to match against S3 ETags and verify file integrity during
        synchronization and uploads.

        Args:
            file_path (str or Path): Path to the local file.

        Returns:
            str or None: The hex-encoded MD5 hash, or None if error occurs.
        """
        hash_md5 = hashlib.md5(usedforsecurity=False)
        try:
            with open(file_path, "rb") as f:
                # Process file in 4KB chunks for memory efficiency
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            _log_error(f"Error calculating MD5 for {file_path}: {e}")
            return None

    def client(self):
        """
        Get or create the boto3 S3 client (singleton pattern).

        Initializes the client once with AWS credentials from config/environment
        and reuses the same instance for all subsequent operations.

        Returns:
            boto3.client: The initialized S3 client.
        """
        if self._client is None:
            aws_key = _get_config('AWS_ACCESS_KEY_ID')
            aws_secret = _get_config('AWS_SECRET_ACCESS_KEY')
            aws_region = _get_config('AWS_REGION', 'us-east-2')

            if aws_key and aws_secret:
                # Use explicit credentials if provided
                self._client = boto3.client(
                    's3',
                    aws_access_key_id=aws_key,
                    aws_secret_access_key=aws_secret,
                    region_name=aws_region
                )
            else:
                # Use default credentials (IAM role, ~/.aws/credentials, etc.)
                self._client = boto3.client('s3', region_name=aws_region)

        return self._client
    
    @property
    def bucket_name(self):
        """
        Get the configured S3 bucket name.

        Returns:
            str or None: The bucket name from environment/config.
        """
        return _get_config('S3_BUCKET')

    def generate_presigned_url(self, s3_url, expires_in=3600):
        """
        Generate a presigned URL for a private S3 object.

        Creates a temporary authenticated URL that allows anyone (including
        external services like eBay) to download the object without AWS
        credentials. Used when listing on eBay since the bucket blocks all
        public access.

        Args:
            s3_url (str): Full S3 URL, e.g.
                ``https://bucket.s3.amazonaws.com/path/to/image.jpg``
            expires_in (int): URL lifetime in seconds. Defaults to 3600 (1 hour).

        Returns:
            str: Presigned URL, or the original URL if generation fails.
        """

        if not s3_url:
            return s3_url
        # Recognize any S3-shaped host: bucket.s3.amazonaws.com,
        # bucket.s3.<region>.amazonaws.com, bucket.s3-accelerate.amazonaws.com,
        # bucket.s3.dualstack.<region>.amazonaws.com, etc.
        try:
            host = urllib.parse.urlparse(s3_url).hostname or ''
        except Exception:
            host = ''
        if not (host.endswith('.amazonaws.com') and ('.s3' in host or host.startswith('s3'))):
            return s3_url

        try:
            parsed = urllib.parse.urlparse(s3_url)
            s3_key = urllib.parse.unquote(parsed.path.lstrip('/'))
            bucket = self.bucket_name

            if not bucket:
                _log_warning("Cannot generate presigned URL: bucket name not configured")
                return s3_url

            url = self.client().generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket, 'Key': s3_key},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as e:
            _log_error(f"Failed to generate presigned URL for {s3_url}: {e}")
            return s3_url

    def get_presigned_urls(self, s3_urls, expires_in=3600):
        """
        Convert a list of S3 URLs to presigned URLs.

        Args:
            s3_urls (list): List of S3 URL strings.
            expires_in (int): URL lifetime in seconds. Defaults to 3600.

        Returns:
            list: Presigned URLs in the same order.
        """
        return [self.generate_presigned_url(url, expires_in) for url in s3_urls if url]

    def optimize_image(self, file_path, max_width=1920, max_height=1920, quality=85):
        """
        Optimize an image before uploading to S3.

        Performs the following optimizations:
        1. Resizes images larger than max dimensions
        2. Converts RGBA/LA/P to RGB with white background
        3. Compresses with specified quality
        4. Removes EXIF data to reduce file size

        This can reduce file sizes by 30-70% while maintaining visual quality,
        resulting in faster page loads and lower S3 storage/transfer costs.

        Args:
            file_path (str or Path): Path to the original image file.
            max_width (int): Maximum width in pixels. Defaults to 1920.
            max_height (int): Maximum height in pixels. Defaults to 1920.
            quality (int): JPEG quality (1-100). Defaults to 85.

        Returns:
            str: Path to the optimized image file, or original if optimization fails.
        """
        try:

            original_path = Path(file_path)

            # Only optimize common image formats
            if original_path.suffix.lower() not in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff']:
                _log_info(f"Skipping optimization for non-image file: {file_path}")
                return str(file_path)

            with Image.open(file_path) as img:
                original_size = original_path.stat().st_size
                needs_optimization = False

                # Check if resizing needed
                if img.width > max_width or img.height > max_height:
                    # Calculate resize ratio maintaining aspect ratio
                    ratio = min(max_width / img.width, max_height / img.height)
                    new_width = int(img.width * ratio)
                    new_height = int(img.height * ratio)
                    img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                    needs_optimization = True
                    _log_info(f"Resized image from {original_path.name}: {img.width}x{img.height}")

                # Convert RGBA/LA/P to RGB
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    # Paste with alpha channel as mask
                    if img.mode in ('RGBA', 'LA'):
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                    needs_optimization = True
                elif img.mode not in ('RGB', 'L'):
                    img = img.convert('RGB')
                    needs_optimization = True

                # Always optimize to remove EXIF and compress
                needs_optimization = True

                # Save optimized version
                optimized_path = original_path.parent / f"{original_path.stem}_optimized.jpg"
                img.save(optimized_path, 'JPEG', quality=quality, optimize=True)

                optimized_size = optimized_path.stat().st_size
                savings_percent = ((original_size - optimized_size) / original_size) * 100

                _log_info(f"Optimized {original_path.name}: {original_size/1024:.1f}KB → {optimized_size/1024:.1f}KB (saved {savings_percent:.1f}%)")

                return str(optimized_path)

        except Exception as e:
            _log_error(f"Error optimizing image {file_path}: {e}")
            # Return original path if optimization fails
            return str(file_path)

    def create_thumbnail(self, file_path, thumbnail_size=(300, 300), quality=85, use_webp=True):
        """
        Generate a thumbnail image from a source image file.

        Resizes the image to fit within the specified dimensions while
        maintaining aspect ratio, converts color space to sRGB for web
        consistency, and optionally outputs in WebP format for efficiency.

        Args:
            file_path (str or Path): Path to the source image file.
            thumbnail_size (tuple): Target (width, height) in pixels. Defaults to (300, 300).
            quality (int): Output quality (1-100). Defaults to 85.
            use_webp (bool): Whether to output WebP format. Defaults to True.

        Returns:
            tuple: (bytes, extension) where bytes is the thumbnail data and extension is '.webp' or '.jpg', or (None, None) on error.
        """
        try:
            # Verify file exists and is readable
            file_path_obj = Path(file_path)
            if not file_path_obj.exists():
                _log_error(f"Thumbnail source file does not exist: {file_path}")
                return None, None

            if file_path_obj.stat().st_size == 0:
                _log_error(f"Thumbnail source file is empty: {file_path}")
                return None, None

            with Image.open(file_path) as img:
                # Verify image format is supported
                if img.format is None:
                    _log_error(f"Cannot identify image format for: {file_path}")
                    return None, None

                # Handle embedded color profiles for accurate color rendering
                icc_profile = img.info.get("icc_profile")
                
                if icc_profile:
                    try:
                        # Convert from embedded profile to sRGB
                        input_profile = io.BytesIO(icc_profile)
                        output_profile = ImageCms.createProfile("sRGB")
                        
                        # Apply the color space transformation
                        img = ImageCms.profileToProfile(img, input_profile, output_profile, renderingIntent=0, outputMode='RGB')
                    except Exception as cms_error:
                        # Fallback if color profile conversion fails
                        _log_warning(f"ImageCms conversion failed for {file_path}, falling back to standard convert: {cms_error}")
                        if img.mode not in ('RGB', 'RGBA'):
                            img = img.convert('RGB')
                elif img.mode not in ('RGB', 'RGBA'):
                    # Convert to RGB if not already (e.g., CMYK to RGB)
                    img = img.convert('RGB')

                # Resize image maintaining aspect ratio
                img.thumbnail(thumbnail_size, Image.Resampling.LANCZOS)

                # Save to bytes buffer
                buffer = io.BytesIO()
                if use_webp:
                    # WebP supports ICC profiles but sRGB is safer as default
                    # We don't necessarily need to embed the profile anymore since we've transformed the pixels
                    img.save(buffer, format='WEBP', quality=quality, method=6)
                    ext = '.webp'
                else:
                    # JPEG supports ICC profiles
                    # Convert RGBA to RGB if needed for JPEG
                    if img.mode == 'RGBA':
                        img = img.convert('RGB')
                    img.save(buffer, format='JPEG', quality=quality, optimize=True)
                    ext = '.jpg'

                buffer.seek(0)
                return buffer.getvalue(), ext
        except Exception as e:
            _log_error(f"Error creating thumbnail for {file_path}: {e}")
            return None, None
    
    def upload_file(self, file_path, s3_key, create_thumb=True, **kwargs):
        """
        Upload a file to S3 and optionally generate a thumbnail.

        Args:
            file_path (str): Local path to the file.
            s3_key (str): Target key (path) in the S3 bucket.
            create_thumb (bool): Whether to generate and upload a thumbnail.
            **kwargs: Additional arguments (ignored for compatibility).

        Returns:
            dict or None: Metadata about uploaded files (urls) or None if error.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name:
                _log_error("S3_BUCKET not configured")
                return None

            # Ensure image is in the user's images folder unless the key
            # is already fully qualified (starts with a known prefix).
            images_prefix = get_user_s3_images_prefix()
            s3_folder = _get_config('S3_FOLDER', 'production')
            known_prefixes = (f'{s3_folder}/', 'users/', 'exports/', 'deleted/')
            if not any(s3_key.startswith(p) for p in known_prefixes):
                s3_key = f"{images_prefix}{s3_key}"

            # Upload full image (bucket policy handles public access)
            self.client().upload_file(
                file_path,
                bucket_name,
                s3_key
            )
            full_url = f"https://{bucket_name}.s3.amazonaws.com/{s3_key}"

            thumb_url = None
            if create_thumb:
                # Create WebP thumbnail (smaller file size)
                thumb_data, thumb_ext = self.create_thumbnail(file_path, use_webp=True)
                if thumb_data:
                    # Create thumbnail S3 key
                    base_name, _ = os.path.splitext(s3_key)
                    thumb_key = f"{base_name}_thumb{thumb_ext}"

                    # Upload thumbnail (bucket policy handles public access)
                    content_type = 'image/webp' if thumb_ext == '.webp' else 'image/jpeg'
                    self.client().put_object(
                        Bucket=bucket_name,
                        Key=thumb_key,
                        Body=thumb_data,
                        ContentType=content_type
                    )
                    thumb_url = f"https://{bucket_name}.s3.amazonaws.com/{thumb_key}"

            return {'full': full_url, 'thumb': thumb_url}
        except ClientError as e:
            _log_error(f"Error uploading {file_path} to S3: {e}")
            return None
        except Exception as e:
            _log_error(f"Unexpected error uploading {file_path}: {e}")
            return None
    
    def download_file(self, s3_key, local_path):
        """
        Download a file from S3 to a local path.

        Args:
            s3_key (str): The S3 key (path) of the file to download.
            local_path (str): Local file path where to save the downloaded file.

        Returns:
            bool: True if successful, False otherwise.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name:
                _log_error("S3_BUCKET not configured")
                return False

            # Ensure parent directory exists
            local_file = Path(local_path)
            local_file.parent.mkdir(parents=True, exist_ok=True)

            # Download the file
            self.client().download_file(bucket_name, s3_key, str(local_path))
            return True

        except ClientError as e:
            # Check if it's a 404 error (file not found)
            if e.response['Error']['Code'] == '404' or e.response['Error']['Code'] == 'NoSuchKey':
                pass
            else:
                _log_error(f"Error downloading {s3_key} from S3: {e}")
            return False
        except Exception as e:
            _log_error(f"Unexpected error downloading {s3_key}: {e}")
            return False

    def delete_file(self, s3_url, delete_thumbnail=True):
        """
        Delete a file and optionally its thumbnail from the S3 bucket.
        
        Extracts the S3 key from the provided URL. For safety, it restricts 
        deletions to the configured images folder ({s3_folder}/images/).
        
        Args:
            s3_url (str): The full HTTPS URL of the S3 object to delete.
            delete_thumbnail (bool): Whether to also attempt deleting the 
                                     associated thumbnail. Defaults to True.
            
        Returns:
            bool: True if the primary file deletion was successful (or if the 
                  file didn't exist), False otherwise.
        """
        try:
            if not s3_url or not s3_url.startswith('https://'):
                _log_warning(f"Invalid or non-HTTPS URL provided for deletion: {s3_url}")
                return False

            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name:
                _log_error("S3_BUCKET not configured - cannot delete file")
                return False

            # Parse the S3 key from URL
            # Handles formats:
            # - https://bucket.s3.amazonaws.com/key
            # - https://bucket.s3.region.amazonaws.com/key
            # - https://s3.amazonaws.com/bucket/key
            # - https://s3.region.amazonaws.com/bucket/key
            
            # Decode any URL encoding (e.g., %20 -> space)
            s3_url_decoded = urllib.parse.unquote(s3_url)

            s3_key = None
            if '.s3.amazonaws.com/' in s3_url_decoded:
                s3_key = s3_url_decoded.split('.s3.amazonaws.com/')[1]
            elif '.s3.' in s3_url_decoded and '.amazonaws.com/' in s3_url_decoded:
                # Handle region-specific endpoint: bucket.s3.region.amazonaws.com/key
                parts = s3_url_decoded.split('.amazonaws.com/')
                if len(parts) == 2:
                    s3_key = parts[1]
            elif 's3.amazonaws.com/' in s3_url_decoded:
                # Handle path-style: s3.amazonaws.com/bucket/key
                parts = s3_url_decoded.split('s3.amazonaws.com/')[1].split('/', 1)
                if len(parts) == 2:
                    s3_key = parts[1]
            elif '/s3.' in s3_url_decoded and '.amazonaws.com/' in s3_url_decoded:
                # Handle path-style region: s3.region.amazonaws.com/bucket/key
                parts = s3_url_decoded.split('.amazonaws.com/')[1].split('/', 1)
                if len(parts) == 2:
                    s3_key = parts[1]

            if not s3_key:
                _log_error(f"Could not parse S3 key from URL: {s3_url}")
                return False

            # Safety check: only delete files from an images folder
            images_prefix = _get_images_prefix()
            user_images_prefix = get_user_s3_images_prefix()
            if not (s3_key.startswith(images_prefix) or s3_key.startswith(user_images_prefix)):
                _log_warning(f"Refusing to delete file outside images folder: {s3_key}")
                return False

            # Delete the main image
            self.client().delete_object(Bucket=bucket_name, Key=s3_key)
            _log_info(f"Deleted main image from S3: {s3_key}")

            # Delete the thumbnail if requested
            if delete_thumbnail:
                base_name, _ = os.path.splitext(s3_key)
                
                # Try to delete both .webp and .jpg thumbnails just in case
                thumbnail_deleted = False
                for ext in ['.webp', '.jpg']:
                    thumb_key = f"{base_name}_thumb{ext}"
                    try:
                        self.client().delete_object(Bucket=bucket_name, Key=thumb_key)
                        _log_info(f"Deleted thumbnail from S3: {thumb_key}")
                        thumbnail_deleted = True
                    except ClientError as thumb_error:
                        # Check if it's a "not found" error (which is fine) or an actual error
                        error_code = thumb_error.response.get('Error', {}).get('Code', '')
                        if error_code == 'NoSuchKey' or error_code == '404':
                            _log_info(f"Thumbnail not found (already deleted or never existed): {thumb_key}")
                        else:
                            _log_warning(f"Error deleting thumbnail {thumb_key}: {thumb_error}")
                    except Exception as thumb_error:
                        _log_warning(f"Unexpected error deleting thumbnail {thumb_key}: {thumb_error}")

                if not thumbnail_deleted:
                    _log_info(f"No thumbnails found to delete for: {base_name}")

            return True
        except ClientError as e:
            _log_error(f"Error deleting {s3_url} from S3: {e}")
            return False
        except Exception as e:
            _log_error(f"Unexpected error deleting {s3_url}: {e}")
            return False
    
    def list_all_files(self):
        """
        List all objects currently stored in the configured S3 bucket.
        
        Handles pagination automatically to retrieve the complete list.
        
        Returns:
            list: List of dictionaries, each containing 'Key', 'Size', 
                  and 'LastModified' for an object.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')

            paginator = self.client().get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name)

            objects = []
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        objects.append({
                            'Key': obj['Key'],
                            'Size': obj['Size'],
                            'LastModified': obj['LastModified']
                        })

            return objects

        except ClientError as e:
            _log_error(f"Error listing objects from S3: {e}")
            return []
        except Exception as e:
            _log_error(f"Unexpected error: {e}")
            return []

    def backup_sku_to_s3(self, sku_value, username=None):
        """
        Backup the current SKU counter value to S3 for persistent state.
        Uses user-specific S3 prefix for multi-user isolation.

        Note: put_object automatically overwrites existing objects with the same key.
        No need to delete first - S3 handles this atomically.
        
        Args:
            sku_value: Current SKU value to backup (int, str, or Path to SKU file).
            username (str, optional): Username for S3 prefix. If None, uses session user.
            
        Returns:
            bool: True if backup was successful, False otherwise.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name:
                _log_error("S3_BUCKET not configured - cannot backup SKU")
                return False

            # Get user-specific SKU prefix
            user_sku_prefix = get_user_s3_sku_prefix(username)
            sku_key = f'{user_sku_prefix}sku.txt'

            # Determine content to upload
            content = None
                        # 1. Handle Path objects explicitly
            if isinstance(sku_value, Path):
                if sku_value.exists() and sku_value.is_file():
                    with open(sku_value, 'r') as f:
                        content = f.read().strip()
                else:
                    _log_error(f"SKU Path object does not exist or is not a file: {sku_value}")
                    return False
            
            # 2. Handle numeric types (int, float)
            elif isinstance(sku_value, (int, float)):
                content = str(int(sku_value))
            
            # 3. Handle strings
            elif isinstance(sku_value, str):
                # Check if it's a numeric string first
                if sku_value.strip().isdigit():
                    content = sku_value.strip()
                else:
                    # If not numeric, check if it's a path string
                    try:
                        path_obj = Path(sku_value)
                        if path_obj.exists() and path_obj.is_file():
                            with open(path_obj, 'r') as f:
                                content = f.read().strip()
                        else:
                            _log_error(f"Invalid SKU value (not a number and not a valid path): {sku_value}")
                            return False
                    except (TypeError, OSError):
                        _log_error(f"Invalid SKU value type/format: {sku_value}")
                        return False

            if content is None or not content.strip().isdigit():
                _log_error(f"Final SKU content is not numeric: '{content}'")
                return False

            content = content.strip()

            # Upload SKU value as text file (overwrites existing)
            response = self.client().put_object(
                Bucket=bucket_name,
                Key=sku_key,
                Body=f"{content}\n".encode('utf-8'),
                ContentType='text/plain'
            )

            return True

        except ClientError as e:
            _log_error(f"Error backing up SKU to S3: {e}")
            _log_error(f"  Bucket: {_get_config('S3_BUCKET')}, Key: production/sku.txt")
            return False
        except Exception as e:
            _log_error(f"Unexpected error backing up SKU: {e}")
            return False

    def restore_sku_from_s3(self, username=None):
        """
        Retrieve the SKU counter value from S3.
        Uses user-specific S3 prefix for multi-user isolation.

        Args:
            username (str, optional): Username for S3 prefix. If None, uses session user.

        Returns:
            dict or None: Metadata about the SKU ({'sku': int, 'last_modified': dt})
                          or None if the file is missing or an error occurs.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name:
                _log_error("S3_BUCKET not configured - cannot restore SKU")
                return None

            # Get user-specific SKU prefix
            user_sku_prefix = get_user_s3_sku_prefix(username)
            sku_key = f'{user_sku_prefix}sku.txt'

            # Download SKU value from S3
            response = self.client().get_object(
                Bucket=bucket_name,
                Key=sku_key
            )

            content = response['Body'].read().decode('utf-8').strip()
            last_modified = response['LastModified']

            try:
                sku_value = int(content)
                _log_info(f"Restored SKU from S3: {sku_value} (key: {sku_key})")
                return {'sku': sku_value, 'last_modified': last_modified}
            except ValueError:
                _log_error(f"Invalid SKU value in S3: '{content}' (not a number)")
                return None

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                pass  # SKU file doesn't exist yet for this user
            else:
                _log_error(f"Error restoring SKU from S3: {e}")
            return None
        except Exception as e:
            _log_error(f"Unexpected error restoring SKU: {e}")
            return None

    def backup_main_csv_to_s3(self, csv_file_path, username=None):
        """
        Backup the primary inventory CSV to S3 for state persistence.
        Uses user-specific S3 prefix for multi-user isolation.

        Uses MD5 checksum comparison to avoid redundant uploads if the 
        file content hasn't changed.
        
        Args:
            csv_file_path (str or Path): Path to the local CSV file.
            username (str, optional): Username for S3 prefix. If None, uses session user.

        Returns:
            bool: True if the backup was successful or skipped due to no 
                  changes, False if an error occurred.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name:
                return False

            if not os.path.exists(csv_file_path):
                _log_warning(f"Main CSV file not found for backup: {csv_file_path}")
                return False

            # Calculate local file MD5
            with open(csv_file_path, 'rb') as f:
                local_md5 = hashlib.md5(f.read()).hexdigest()

            # Get user-specific CSV prefix
            user_csv_prefix = get_user_s3_csv_prefix(username)
            csv_key = f'{user_csv_prefix}items.csv'

            # Get S3 file MD5 (ETag)
            s3_md5 = None
            try:
                response = self.client().head_object(Bucket=bucket_name, Key=csv_key)
                # S3 ETag is MD5 hash wrapped in quotes for single-part uploads
                s3_etag = response.get('ETag', '').strip('"')
                s3_md5 = s3_etag
            except self.client().exceptions.NoSuchKey:
                # File doesn't exist in S3 yet for this user
                s3_md5 = None
            except Exception as e:
                _log_warning(f"Could not get S3 file metadata: {e}")

            # Only upload if content has changed
            if s3_md5 and s3_md5 == local_md5:
                return True

            self.client().upload_file(csv_file_path, bucket_name, csv_key)
            return True

        except Exception as e:
            _log_error(f"Error backing up main CSV to S3: {e}")
            return False

    def restore_main_csv_from_s3(self, username=None):
        """
        Download the primary inventory CSV from S3.

        Args:
            username (str, optional): Username for S3 prefix. If None, uses session user.
        
        Returns:
            dict or None: Metadata and content ({'content': bytes, 'last_modified': dt})
                          or None if the file is missing or an error occurs.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name:
                return None

            s3_folder = _get_config('S3_FOLDER', 'production')

            # Try user-specific CSV prefix first, fall back to legacy path
            user_csv_prefix = get_user_s3_csv_prefix(username)
            csv_key = f'{user_csv_prefix}items.csv'

            try:
                response = self.client().get_object(Bucket=bucket_name, Key=csv_key)
            except ClientError as e:
                if e.response['Error']['Code'] == 'NoSuchKey':
                    # Fall back to legacy path for backward compatibility
                    legacy_key = f'{s3_folder}/csv/items.csv'
                    response = self.client().get_object(Bucket=bucket_name, Key=legacy_key)
                else:
                    raise
            content = response['Body'].read()
            last_modified = response['LastModified']

            return {
                'content': content,
                'last_modified': last_modified
            }

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                pass
            else:
                _log_error(f"Error restoring main CSV from S3: {e}")
            return None
        except Exception as e:
            _log_error(f"Unexpected error restoring main CSV: {e}")
            return None

    def backup_csv_to_s3(self, csv_file_path, cleanup_local_exports=True):
        """
        Backup a CSV export to S3 with a unique timestamp.
        Uses user-specific S3 prefix for multi-user isolation.

        This is used for historical tracking of exports. It also handles 
        maintenance by cleaning up old local export files.
        
        Args:
            csv_file_path (str or Path): Path to the CSV file to backup.
            cleanup_local_exports (bool): Whether to trigger local cleanup. 
                                          Defaults to True.
                                          
        Returns:
            bool: True if the backup was successful.
        """
        try:

            bucket_name = _get_config('S3_BUCKET')

            if not bucket_name:
                _log_error("S3_BUCKET not configured - cannot backup CSV")
                return False

            csv_path = Path(csv_file_path)
            if not csv_path.exists():
                _log_warning(f"CSV file not found: {csv_file_path}")
                return False

            # Get user-specific exports prefix
            user_exports_prefix = get_user_s3_exports_prefix()

            # Create timestamped filename: users/{username}/exports/2024-12-21_1430_comics_export.csv
            timestamp = datetime.now().strftime('%Y-%m-%d_%H%M')
            timestamped_filename = f'{timestamp}_comics_export.csv'
            s3_key = f'{user_exports_prefix}{timestamped_filename}'

            # Upload CSV to S3 (kept permanently)
            self.client().upload_file(str(csv_path), bucket_name, s3_key)
            _log_info(f"Backed up CSV export to S3: {s3_key}")

            # Save a local timestamped copy to user-specific exports directory
            exports_dir = get_user_exports_dir()
            exports_dir.mkdir(parents=True, exist_ok=True)

            local_export_path = exports_dir / timestamped_filename
            shutil.copy2(csv_path, local_export_path)

            # Clean up old LOCAL exports - keep only last 100 on server
            if cleanup_local_exports:
                self._cleanup_old_local_exports()

            return True

        except ClientError as e:
            _log_error(f"Error backing up CSV to S3: {e}")
            return False
        except Exception as e:
            _log_error(f"Unexpected error backing up CSV: {e}")
            return False


    def _cleanup_old_local_exports(self, keep_count=100):
        """
        Clean up old CSV exports from LOCAL server storage, keeping only the most recent ones.
        S3 exports are kept permanently - this only cleans the server's instance/exports/ folder.

        Args:
            keep_count: Number of recent exports to keep on server (default: 100)
        """
        try:

            # Get user-specific exports directory
            exports_dir = get_user_exports_dir()

            # Create exports directory if it doesn't exist
            if not exports_dir.exists():
                exports_dir.mkdir(parents=True, exist_ok=True)
                return

            # List all CSV files in exports directory
            export_files = sorted(
                [f for f in exports_dir.glob('*_comics_export.csv')],
                key=lambda x: x.stat().st_mtime
            )

            # Delete old exports if we have more than keep_count
            if len(export_files) > keep_count:
                files_to_delete = export_files[:-keep_count]  # Keep the last keep_count
                for file_path in files_to_delete:
                    try:
                        file_path.unlink()
                    except Exception as e:
                        _log_warning(f"Failed to delete local export {file_path.name}: {e}")


        except Exception as e:
            _log_warning(f"Error cleaning up old local exports: {e}")
            # Don't fail the backup if cleanup fails

    def get_storage_stats(self):
        """
        Calculate total storage statistics for the S3 bucket.
        
        Counts the total number of images and calculates their combined 
        byte size.
        
        Returns:
            dict: Statistics containing 'image_count' and 'total_image_size'.
        """
        bucket_name = _get_config('S3_BUCKET')
        image_count = 0
        total_image_size = 0

        if bucket_name:
            try:
                paginator = self.client().get_paginator('list_objects_v2')
                pages = paginator.paginate(Bucket=bucket_name, Prefix=get_user_s3_images_prefix())

                for page in pages:
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            # Skip thumbnails
                            if '_thumb' not in obj['Key']:
                                image_count += 1
                                total_image_size += obj['Size']
            except Exception as e:
                _log_error(f"Error counting S3 images: {e}")

        return {
            'image_count': image_count,
            'total_image_size': total_image_size
        }

    def delete_all_files(self):
        """
        Delete all image files from the S3 bucket (images folder only).
        Preserves: csv/, sku.txt, exports/, and deleted/

        Returns:
            tuple: (success: bool, count: int) - success status and number of files deleted
        """
        try:
            bucket_name = _get_config('S3_BUCKET')

            images_prefix = _get_images_prefix()

            # Also include user-specific images prefix
            user_images_prefix = get_user_s3_images_prefix()

            # List all objects under both prefixes
            paginator = self.client().get_paginator('list_objects_v2')

            objects_to_delete = []
            for prefix in [images_prefix, user_images_prefix]:
                pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
                for page in pages:
                    if 'Contents' in page:
                        for obj in page['Contents']:
                            objects_to_delete.append({'Key': obj['Key']})

            if not objects_to_delete:
                return True, 0

            # Delete objects in batches of 1000 (AWS limit)
            for i in range(0, len(objects_to_delete), 1000):
                batch = objects_to_delete[i:i + 1000]
                self.client().delete_objects(
                    Bucket=bucket_name,
                    Delete={'Objects': batch}
                )

            return True, len(objects_to_delete)

        except ClientError as e:
            _log_error(f"Error deleting objects from S3: {e}")
            return False, 0
        except Exception as e:
            _log_error(f"Unexpected error: {e}")
            return False, 0


    def delete_files(self, keys):
        """
        Delete multiple files from S3 by their keys.

        Args:
            keys: List of S3 object keys to delete

        Returns:
            int: Number of files deleted
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            if not bucket_name or not keys:
                return 0

            deleted_count = 0
            # Delete in batches of 1000 (S3 limit)
            for i in range(0, len(keys), 1000):
                batch = keys[i:i + 1000]
                objects_to_delete = [{'Key': key} for key in batch]
                self.client().delete_objects(
                    Bucket=bucket_name,
                    Delete={'Objects': objects_to_delete}
                )
                deleted_count += len(batch)

            return deleted_count

        except Exception as e:
            _log_error(f"Error deleting files from S3: {e}")
            return 0


    def _bidirectional_sync(self, local_dir, s3_prefix, label="files"):
        """
        Internal generalized method for bi-directional synchronization.
        
        Args:
            local_dir (Path): The local directory to sync.
            s3_prefix (str): The S3 prefix (folder) to sync with.
            label (str): Human-readable label for logging.
            
        Returns:
            dict: Summary of results (downloaded, uploaded, skipped).
        """
        try:
            bucket_name = self.bucket_name
            if not bucket_name:
                return None

            local_files = {f.name: f for f in local_dir.iterdir() if f.is_file()}
            paginator = self.client().get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name, Prefix=s3_prefix)
            
            summary = {'downloaded': 0, 'uploaded': 0, 'skipped': 0, 'errors': 0}
            s3_keys_processed = set()
            s3_objects_found = 0
            
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        s3_objects_found += 1
                        s3_key = obj['Key']
                        if s3_key == s3_prefix: # Skip the prefix folder itself
                            continue
                            
                        file_name = os.path.basename(s3_key)
                        s3_keys_processed.add(file_name)
                        local_path = local_dir / file_name
                        
                        s3_mtime = obj['LastModified'].replace(tzinfo=timezone.utc).timestamp()
                        s3_etag = obj['ETag'].strip('"')
                        
                        if not local_path.exists():
                            # S3 -> Local
                            self._retry_operation(self.client().download_file, bucket_name, s3_key, str(local_path))
                            summary['downloaded'] += 1
                        else:
                            local_mtime = local_path.stat().st_mtime
                            
                            # Content check using MD5/ETag
                            local_md5 = self._calculate_md5(local_path)
                            if local_md5 == s3_etag:
                                summary['skipped'] += 1
                                continue

                            # Decision logic: Newest wins
                            if s3_mtime > local_mtime + 2:
                                # S3 -> Local
                                self._retry_operation(self.client().download_file, bucket_name, s3_key, str(local_path))
                                summary['downloaded'] += 1
                            else:
                                # Local -> S3
                                self._retry_operation(self.client().upload_file, str(local_path), bucket_name, s3_key)
                                summary['uploaded'] += 1
            
            # Handle Local-only files
            for file_name, file_path in local_files.items():
                if file_name not in s3_keys_processed:
                    try:
                        # Skip if file no longer exists (temp files may be deleted)
                        if not file_path.exists():
                            continue

                        s3_key = f"{s3_prefix}{file_name}"
                        self._retry_operation(self.client().upload_file, str(file_path), bucket_name, s3_key)
                        summary['uploaded'] += 1
                    except FileNotFoundError:
                        # File was deleted between directory scan and upload attempt (temp file cleanup)
                        # Use debug level via _log_info to avoid log spam
                        continue
                    except Exception as e:
                        _log_warning(f"Failed to upload {file_name}: {e}")
                        summary['errors'] += 1

            return summary
            
        except Exception as e:
            _log_error(f"Error in bi-directional {label} sync: {e}")
            return None

    def sync_images_from_s3(self, username=None):
        """
        Synchronize the local image directory with S3 (bi-directional).
        
        Args:
            username (str, optional): Username to sync for. If None, uses current session user.

        Returns:
            dict: Summary of the sync results (downloaded, uploaded, skipped).
        """

        local_images_dir = get_user_images_dir(username)
        local_images_dir.mkdir(parents=True, exist_ok=True)
        
        s3_images_prefix = get_user_s3_images_prefix(username)
        return self._bidirectional_sync(local_images_dir, s3_images_prefix, label="images")

    def sync_exports_from_s3(self, username=None):
        """
        Synchronize the local exports directory with S3 (bi-directional).
        
        Args:
            username (str, optional): Username to sync for. If None, uses current session user.

        Returns:
            dict: Summary of the sync results (downloaded, uploaded, skipped).
        """

        exports_dir = get_user_exports_dir(username)
        exports_dir.mkdir(parents=True, exist_ok=True)
        
        # Enforce local limit before sync
        self._cleanup_old_local_exports(keep_count=100)
        
        s3_exports_prefix = get_user_s3_exports_prefix(username)
        return self._bidirectional_sync(exports_dir, s3_exports_prefix, label="exports")

    def duplicate_images(self, target_sku, image_urls_to_copy):
        """
        Duplicate a set of images in S3 for a new SKU.
        
        Args:
            target_sku (str): The SKU to assign to the copies.
            image_urls_to_copy (list): List of S3 URLs to be duplicated.
            
        Returns:
            list: List of new S3 URLs for the duplicated images.
        """
        new_urls = []
        bucket_name = self.bucket_name
        if not bucket_name:
            return []

        images_prefix = get_user_s3_images_prefix()

        for image_url in image_urls_to_copy:
            if not image_url or images_prefix not in image_url:
                continue

            try:
                # Extract the old key and filename
                old_key = image_url.split(images_prefix)[1]
                old_full_key = f'{images_prefix}{old_key}'

                # Create new key with target SKU
                if '_' in old_key:
                    file_suffix = old_key.split('_', 1)[1]
                    new_key = f'{target_sku}_{file_suffix}'
                    new_full_key = f'{images_prefix}{new_key}'

                    # 1. Copy main image in S3
                    self.client().copy_object(
                        CopySource={'Bucket': bucket_name, 'Key': old_full_key},
                        Bucket=bucket_name,
                        Key=new_full_key
                    )

                    # 2. Build the new URL
                    new_image_url = image_url.replace(old_key, new_key)
                    new_urls.append(new_image_url)

                    # 3. Handle thumbnail duplication if it exists
                    old_thumb_key = old_full_key.replace('.jpg', '_thumb.webp').replace('.png', '_thumb.webp')
                    new_thumb_key = new_full_key.replace('.jpg', '_thumb.webp').replace('.png', '_thumb.webp')
                    
                    try:
                        self.client().copy_object(
                            CopySource={'Bucket': bucket_name, 'Key': old_thumb_key},
                            Bucket=bucket_name,
                            Key=new_thumb_key
                        )
                    except Exception:
                        pass # Thumbnail might not exist

                    # 4. Download locally for consistency
                    try:

                        local_images_dir = get_user_images_dir()
                        local_images_dir.mkdir(parents=True, exist_ok=True)
                        
                        local_image_path = local_images_dir / new_key
                        self.client().download_file(bucket_name, new_full_key, str(local_image_path))
                        
                        # Also try downloading thumbnail
                        new_thumb_filename = new_key.replace('.jpg', '_thumb.webp').replace('.png', '_thumb.webp')
                        local_thumb_path = local_images_dir / new_thumb_filename
                        try:
                            self.client().download_file(bucket_name, new_thumb_key, str(local_thumb_path))
                        except Exception:
                            pass
                    except Exception as dl_err:
                        _log_warning(f"Failed to download duplicated image locally: {dl_err}")

            except Exception as e:
                _log_error(f"Error duplicating image {image_url}: {e}")

        return new_urls

    def list_images_in_s3(self, prefix):
        """
        List all image files in S3 under a specific prefix.

        Args:
            prefix (str): S3 prefix to search under (e.g., 'production/images/')

        Returns:
            set: Set of image filenames found under the prefix
        """
        try:
            bucket_name = _get_config('S3_BUCKET')

            paginator = self.client().get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)

            filenames = set()
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        key = obj['Key']
                        # Extract filename from key
                        filename = key.split('/')[-1]
                        if filename and not key.endswith('/'):  # Skip directories
                            filenames.add(filename)

            return filenames

        except ClientError as e:
            _log_error(f"Error listing images in S3: {e}")
            return set()
        except Exception as e:
            _log_error(f"Unexpected error listing images: {e}")
            return set()
    def backup_user_preferences_to_s3(self, user_prefs_file_path):
        """
        Backup the user preferences JSON file to S3 for state persistence across redeployments.

        Uses MD5 checksum comparison to avoid redundant uploads if the
        file content hasn't changed.

        Args:
            user_prefs_file_path (str or Path): Path to the local user_preferences.json file.

        Returns:
            bool: True if the backup was successful or skipped due to no
                  changes, False if an error occurred.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            config_prefix = get_user_s3_config_prefix()
            if not bucket_name:
                return False

            user_prefs_path = Path(user_prefs_file_path)
            if not user_prefs_path.exists():
                _log_warning(f"User preferences file not found for backup: {user_prefs_file_path}")
                return False

            # Calculate local file MD5
            with open(user_prefs_path, 'rb') as f:
                local_md5 = hashlib.md5(f.read()).hexdigest()

            # Get S3 file MD5 (ETag)
            s3_md5 = None
            prefs_key = f'{config_prefix}user_preferences.json'
            try:
                response = self.client().head_object(Bucket=bucket_name, Key=prefs_key)
                s3_etag = response.get('ETag', '').strip('"')
                s3_md5 = s3_etag
            except self.client().exceptions.NoSuchKey:
                s3_md5 = None
            except Exception as e:
                _log_warning(f"Could not get S3 user preferences metadata: {e}")

            # Only upload if content has changed
            if s3_md5 and s3_md5 == local_md5:
                return True

            self.client().upload_file(str(user_prefs_path), bucket_name, prefs_key)
            _log_info(f"User preferences backed up to S3")
            return True

        except ClientError as e:
            _log_error(f"Error backing up user preferences to S3: {e}")
            return False
        except Exception as e:
            _log_error(f"Unexpected error backing up user preferences: {e}")
            return False

    def restore_user_preferences_from_s3(self):
        """
        Retrieve the user preferences JSON file from S3.

        Returns:
            dict or None: Metadata and content ({'content': dict, 'last_modified': dt})
                          or None if the file is missing or an error occurs.
        """
        try:
            bucket_name = _get_config('S3_BUCKET')
            config_prefix = get_user_s3_config_prefix()
            prefs_key = f'{config_prefix}user_preferences.json'

            if not bucket_name:
                _log_warning("S3_BUCKET not configured - cannot restore user preferences")
                return None

            # Download user preferences from S3
            response = self.client().get_object(
                Bucket=bucket_name,
                Key=prefs_key
            )

            content = json.loads(response['Body'].read().decode('utf-8'))
            last_modified = response['LastModified']

            return {'content': content, 'last_modified': last_modified}

        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                _log_info(f"User preferences not found in S3 (this is OK on first deploy)")
            else:
                _log_error(f"Error restoring user preferences from S3: {e}")
            return None
        except Exception as e:
            _log_error(f"Unexpected error restoring user preferences: {e}")
            return None


# Singleton instance
s3_service = S3Service()
