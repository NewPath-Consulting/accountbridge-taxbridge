AIMatic Lambda Deployment Stack - README
========================================

Prerequisites:
--------------
  • AWS account with permissions to create Lambda, IAM roles, and ECR access.
  • Access to AWS CloudFormation console or AWS CLI.
  • ECR repository containing the Docker image for the Lambda function.

Deployment Instructions:
------------------------
  • Open the AWS CloudFormation console or use AWS CLI.
  • Upload the template file: AIMaticLambdaStack.yaml.
  • Configure the parameters according to your requirements:

      Example:
        • Environment = sandbox-prod
        • ResourceName = AIMatic
        • ECRRepositoryUri = <Your ECR URI>
        • ImageTag = latest

  • Adjust Lambda resource settings in the template if needed:
        • MemorySize – RAM allocated to the function (default: 2048 MB)
        • Timeout – Maximum execution time in seconds (default: 900)
        • EphemeralStorage – Lambda temporary storage in MB (default: 512 MB)
        • Add the IAM Policies permissions based on the requirement. 

  • Click Create Stack (or run via CLI using:
      aws cloudformation create-stack --stack-name <StackName> --template-body file://AIMaticLambdaStack.yaml --parameters ParameterKey=Environment,ParameterValue=sandbox-prod ...)

Outputs from the Template:
--------------------------
  • After deployment, you can find the names or identifiers of the Lambda resources you created:

        • Friendly Name – The name you gave in ResourceName.
        • Function Name – The actual deployed Lambda name (ResourceName-Environment).
        • Function ARN – The unique Lambda ARN.
        • Function URL – Public URL for invoking the Lambda function.

Important Notes:
----------------
  • Ensure the Docker image in ECR is accessible and tagged correctly.
  • IAM role grants Lambda permissions to ECR, Textract, Bedrock, and S3.
  • Adjust memory, timeout, and ephemeral storage values based on expected workload.
  • The Lambda function URL is publicly accessible (AuthType: NONE) – secure it if needed.