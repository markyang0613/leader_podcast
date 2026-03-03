import boto3
import os
from datetime import datetime

def upload_to_s3(file_name, bucket_name):
    # Ensure keys are loaded from environment
    s3 = boto3.client('s3', 
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("AWS_SECRET_KEY")
    )
    
    date_str = datetime.now().strftime("%Y-%m-%d")
    s3_path = f"podcasts/{date_str}_tech.mp3"
    
    s3.upload_file(file_name, bucket_name, s3_path)
    
    # This URL is what you will eventually store in your database
    return f"https://{bucket_name}.s3-ap-northeast-2.amazonaws.com/{s3_path}"