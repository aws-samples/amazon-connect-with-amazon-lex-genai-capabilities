FROM public.ecr.aws/lambda/python:3.10

COPY dependencies ${LAMBDA_TASK_ROOT}

RUN pip3 install -r ${LAMBDA_TASK_ROOT}/requirements.txt -t .

COPY app/lambda_function.py ${LAMBDA_TASK_ROOT}

CMD ["lambda_function.lambda_handler"]