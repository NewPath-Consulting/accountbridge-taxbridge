import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional
import logging

from app.adapters.aws_clients import aws_clients
from app.config.settings import settings

logger = logging.getLogger(__name__)

class S3Manager:
    """Async S3 file operations"""
    
    def __init__(self, bucket_name: Optional[str] = None):
        self.s3_client = aws_clients.get_s3()
        self.bucket_name = bucket_name or settings.BUCKET_NAME
    
    async def upload_file(
        self,
        file_path: str,
        document_id: str,
        file_name: Optional[str] = None
    ) -> str:
        """Upload file to S3 asynchronously"""
        
        if not file_name:
            file_name = os.path.basename(file_path)
        
        s3_key = f"{settings.S3_PREFIX}/{document_id}/{file_name}"
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.upload_file(
                    Filename=file_path,
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    ExtraArgs={
                        'ServerSideEncryption': 'AES256',
                        'Metadata': {
                            'document-id': document_id,
                            'upload-time': datetime.utcnow().isoformat()
                        }
                    }
                )
            )
            
            logger.info(f"Uploaded to S3: s3://{self.bucket_name}/{s3_key}")
            return s3_key
            
        except Exception as e:
            logger.error(f"Failed to upload to S3: {str(e)}")
            raise RuntimeError(f"S3 upload failed: {str(e)}")
    
    async def download_file(self, s3_key: str, local_path: str):
        """Download file from S3 asynchronously"""
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.download_file(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                    Filename=local_path
                )
            )
            
            logger.info(f"Downloaded from S3: {s3_key} -> {local_path}")
            
        except Exception as e:
            logger.error(f"Failed to download from S3: {str(e)}")
            raise RuntimeError(f"S3 download failed: {str(e)}")
    
    async def delete_file(self, s3_key: str):
        """Delete file from S3 asynchronously"""
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.delete_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
            )
            
            logger.info(f"Deleted from S3: {s3_key}")
            
        except Exception as e:
            logger.warning(f"Failed to delete from S3: {str(e)}")
    
    async def get_presigned_url(
        self,
        s3_key: str,
        expiration: int = 3600
    ) -> str:
        """Generate presigned URL for S3 object"""
        
        try:
            loop = asyncio.get_event_loop()
            url = await loop.run_in_executor(
                None,
                lambda: self.s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': self.bucket_name,
                        'Key': s3_key
                    },
                    ExpiresIn=expiration
                )
            )
            
            logger.info(f"Generated presigned URL for: {s3_key}")
            return url
            
        except Exception as e:
            logger.error(f"Failed to generate presigned URL: {str(e)}")
            raise RuntimeError(f"Presigned URL generation failed: {str(e)}")
    
    async def file_exists(self, s3_key: str) -> bool:
        """Check if file exists in S3"""
        
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.head_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
            )
            return True
            
        except:
            return False

    async def list_objects(self, prefix: str = "") -> list[str]:
        """List object keys under an optional prefix (handles pagination)."""
        keys: list[str] = []
        continuation_token: Optional[str] = None

        try:
            loop = asyncio.get_event_loop()
            while True:
                kwargs: dict = {
                    "Bucket": self.bucket_name,
                    "Prefix": prefix,
                }
                if continuation_token:
                    kwargs["ContinuationToken"] = continuation_token

                response = await loop.run_in_executor(
                    None,
                    lambda kw=kwargs: self.s3_client.list_objects_v2(**kw),
                )

                for obj in response.get("Contents", []):
                    keys.append(obj["Key"])

                if not response.get("IsTruncated"):
                    break
                continuation_token = response.get("NextContinuationToken")

            return keys

        except Exception as e:
            logger.error("Failed to list S3 objects: %s", e)
            raise RuntimeError(f"S3 list failed: {e}") from e

    async def get_object_bytes(self, s3_key: str) -> bytes:
        """Download an S3 object body as bytes."""
        try:
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.get_object(
                    Bucket=self.bucket_name,
                    Key=s3_key,
                ),
            )
            body = response["Body"].read()
            logger.info("Fetched from S3: s3://%s/%s (%d bytes)", self.bucket_name, s3_key, len(body))
            return body

        except Exception as e:
            logger.error("Failed to get S3 object %s: %s", s3_key, e)
            raise RuntimeError(f"S3 get_object failed: {e}") from e
    
    async def cleanup_old_files(self, days: int = None):
        """Delete files older than specified days"""
        
        if days is None:
            days = settings.S3_TEMP_EXPIRY_DAYS
        
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days)
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.s3_client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=settings.S3_PREFIX
                )
            )
            
            if 'Contents' not in response:
                logger.info("No files to cleanup")
                return
            
            delete_keys = []
            for obj in response['Contents']:
                if obj['LastModified'].replace(tzinfo=None) < cutoff_date:
                    delete_keys.append({'Key': obj['Key']})
            
            if delete_keys:
                await loop.run_in_executor(
                    None,
                    lambda: self.s3_client.delete_objects(
                        Bucket=self.bucket_name,
                        Delete={'Objects': delete_keys}
                    )
                )
                logger.info(f"Cleaned up {len(delete_keys)} old files from S3")
            
        except Exception as e:
            logger.error(f"Failed to cleanup old S3 files: {str(e)}")