import boto3
from botocore.config import Config
from app.config.settings import settings
import logging
import urllib3

logger = logging.getLogger(__name__)

# Configure boto3 with timeouts and retries
boto_config = Config(
    read_timeout=120,
    connect_timeout=10,
    retries={
        'max_attempts': 3,
        'mode': 'adaptive'
    }
)


def _boto3_client(service_name: str):
    """Create a boto3 client, optionally disabling SSL verification."""
    verify = settings.AWS_SSL_VERIFY
    if not verify:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        logger.warning("AWS_SSL_VERIFY=false — SSL certificate verification disabled for %s", service_name)
    return boto3.client(
        service_name,
        region_name=settings.AWS_REGION,
        config=boto_config,
        verify=verify,
    )

class AWSClients:
    """Singleton AWS client manager"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialize_clients()
        return cls._instance

    def _initialize_clients(self):
        """Initialize all AWS clients"""
        try:
            self.textract = _boto3_client("textract")
            self.bedrock = _boto3_client("bedrock-runtime")
            self.s3 = _boto3_client("s3")

            logger.info("AWS clients initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize AWS clients: {str(e)}")
            raise

    def get_textract(self):
        return self.textract

    def get_bedrock(self):
        return self.bedrock

    def get_s3(self):
        return self.s3

# Global instance
aws_clients = AWSClients()