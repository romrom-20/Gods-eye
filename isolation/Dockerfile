FROM python:3.11-slim
WORKDIR /evaluator
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir numpy==2.0.2 MinAtar==1.0.15
COPY godseye /evaluator/godseye
ENV OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 65532:65532
ENTRYPOINT ["python", "-m", "godseye.evaluator", "--state", "/private", "--host", "0.0.0.0"]
