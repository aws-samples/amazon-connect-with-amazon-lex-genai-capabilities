#!/bin/bash

# Check if arguments are supplied
if [ $# -eq 0 ]; then
   echo "No arguments supplied"
   echo -e "Usage:\n `basename $0` aws_region cfn_stackname"
   echo -e "Example:\n `basename $0` us-east-1 mystackname"
   exit 1
elif [ $# -eq 1 ]; then
   echo "One argument supplied"
   echo -e "Usage:\n `basename $0` aws_region cfn_stackname"
   echo -e "Example:\n `basename $0` us-east-1 mystackname"
   exit 1
fi

#Declare variables.
declare -r aws_region=$1
declare -r stackname=$2

echo "Creating stack $stackname in region $aws_region"

#assign the template file name and parameters file name to the variables
declare -r templateFile=file://template.yaml
declare -r paramsFile=file://scripts/parameters.json

#Functions
#-------------------------------------------------------------------------------
# Retrieve the status of a cfn stack
#
# Args:
# $1  aws_region
# $2  stack name
#-------------------------------------------------------------------------------
getStackStatus() {
	aws cloudformation describe-stacks \
		--region $aws_region \
		--stack-name $stackname  \
		--query Stacks[].StackStatus \
		--output text
}

#-------------------------------------------------------------------------------
# Waits for a stack to reach a given status. If the stack ever reports any
# status other thatn *_IN_PROGRESS we will return failure status, as all other
# statuses that are not the one we are waiting for are considered terminal
#
# Args:
# $1  stack name
# $2  The stack status to wait for
#-------------------------------------------------------------------------------
waitForState() {
	local status

	status=$(getStackStatus $stackname)

	while [[ "$status" != "$2" ]]; do
		echo "Waiting for stack $1 to obtain status $2 - Current status: $status"

		# If the status is not one of the "_IN_PROGRESS" status' then consider this as an error
		if [[ "$status" != *"_IN_PROGRESS"* ]]; then
			exitWithErrorMessage "Unexpected status '$status'"
		fi

		status=$(getStackStatus $stackname)

		sleep 5
	done
	echo "Stack $stackname  obtained $2 status"
}



#-------------------------------------------------------------------------------
# Exit the program with error status 1.
#
# Args:
# $1  Error message to display when exiting
#-------------------------------------------------------------------------------
exitWithErrorMessage() {
	echo "ERROR: $stackname"
	exit 1
}


#-------------------------------------------------------------------------------
#Main : Create the stack
#
# Args:
# $1  aws_region
# $2  stack name
# $3  template file
# $4  parameters file
#-------------------------------------------------------------------------------

aws cloudformation create-stack \
	--capabilities CAPABILITY_IAM \
	--disable-rollback \
	--parameters ${paramsFile} \
	--region ${aws_region} \
	--stack-name ${stackname} \
	--template-body ${templateFile}

if ! [ "$?" = "0" ]; then
	exitWithErrorMessage "Cannot create stack ${stackname}!"
fi

# Wait for the stack to be created
waitForState ${stackname} "CREATE_COMPLETE"


	