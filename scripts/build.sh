#!/bin/bash

# Check if arguments are supplied
if [ $# -eq 0 ]; then
   echo "No arguments supplied"
   echo -e "Usage:\n `basename $0` aws_region amazon_ecr_repositoryname"
   echo -e "Example: \n `basename $0` us-east-1 my-ecr-repo"
   exit 1
elif [ $# -eq 1 ]; then
   echo "One argument supplied"
   echo -e "Usage:\n `basename $0` aws_region amazon_ecr_repositoryname"
   echo -e "Example:\n `basename $0` us-east-1 my-ecr-repo"
   exit 1
fi

#Declare variables.
declare -r aws_region=$1
declare -r ecr_repo=$2

# docker login
aws ecr get-login --region $aws_region

# Create ECR repository if it does not exists.
out=$(aws ecr describe-repositories --repository-names ${ecr_repo} --region ${aws_region} 2>/dev/null)
status=$?

if [ $status -gt 0 ]; then
   out=$(aws ecr create-repository --repository-name ${ecr_repo} --region ${aws_region} --image-scanning-configuration scanOnPush=true) 
   repouri=$(echo $out | jq -r '.repository.repositoryUri')
else
   repouri=$(echo $out | jq -r '.repositories[0].repositoryUri')
fi

if [ -z $repouri ]; then
   echo "Error for ${ecr_repo}"
   exit 1
fi

# Build docker image
registry=$(echo $repouri | sed "s/\/$ecr_repo//")
aws ecr get-login-password --region $aws_region | docker login --username AWS --password-stdin $registry
aws ecr put-image-scanning-configuration --repository-name ${ecr_repo} --region ${aws_region}  --image-scanning-configuration scanOnPush=true
status=$?
if [ $status -gt 0 ]; then
   echo "ecr login failed"
   exit 1;
fi
image=${ecr_repo}:latest
docker buildx build --platform linux/amd64 -t ${image} . 
status=$?
if [ $status -gt 0 ]; then
   echo "build failed for ${ecr_repo}"
   exit 1;
fi

# Tag and push docker image to ECR repository
docker tag $image ${repouri}
docker push ${repouri}
status=$?
if [ $status -gt 0 ]; then
   echo "image push failed for ${ecr_repo}"
   exit 1;
fi

# Get the image address from ECR repository
address=$(aws ecr describe-images --repository-name ${ecr_repo} --region ${aws_region}  --query 'imageDetails[*].imageTags[0]' --output json | jq --arg v `aws ecr describe-repositories --repository-name ${ecr_repo} --region ${aws_region} --query 'repositories[0].repositoryUri' --output text` '.[] | ($v + ":" + .)')
echo $address
exit 0;
