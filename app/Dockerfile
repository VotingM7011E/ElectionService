FROM python:3.13.7-alpine

WORKDIR /app

COPY requirements.txt /app
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt

COPY ./src /app

ENTRYPOINT ["python3"]
CMD ["app.py"]