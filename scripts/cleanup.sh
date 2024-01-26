#!/bin/bash

# Check if arguments are supplied
if [ $# -eq 0 ]; then
   echo "No arguments supplied, three arguments required"
   echo -e "Usage: \n `basename $0` aws_region amazon_ecr_repositoryname cfn_stackname"
   echo -e "Example:\n `basename $0` us-east-1 my-ecr-repo mystackname"
   exit 1
elif [ $# -eq 1 ]; then
   echo "One arguments supplied, three arguments required"
   echo -e "Usage:\n `basename $0` aws_region amazon_ecr_repositoryname cfn_stackname"
   echo -e "Example:\n `basename $0` us-east-1 my-ecr-repo mystackname"
   exit 1
elif [ $# -eq 2 ]; then
   echo "Two arguments supplied, three arguments required"
   echo -e "Usage:\n `basename $0` aws_region amazon_ecr_repositoryname cfn_stackname"
   echo -e "Example:\n `basename $0` us-east-1 my-ecr-repo mystackname"
   exit 1
fi

#Declare variables.
declare -r aws_region=$1
declare -r ecr_repo=$2
declare -r stackname=$3

#Check for function exit code and display appropriate message.
checkexitcode() {
  exit_code="$1"
  message="$2"

  if [[ "$?" == "${exit_code}" ]]
  then
    echo "${message}"
  else
    echo "Error occured. Please verify your configurations and try again."
  fi
}


#Delete the ECR Image repository
aws ecr delete-repository --repository-name ${ecr_repo} --region ${aws_region} --force
checkexitcode "$?" "Successfully deleted ECR repository."


#Delete the CloudFormation stack
aws cloudformation delete-stack --stack-name ${stackname} --region ${aws_region} >> /dev/null
checkexitcode "$?" "Successfully deleted CloudFormation stack."

