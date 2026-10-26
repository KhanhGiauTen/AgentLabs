FROM python:3.11.14-slim
RUN pip install --no-cache-dir numpy==2.3.4 scipy==1.16.3 scikit-learn==1.7.2 pandas==2.3.3 matplotlib==3.10.7
WORKDIR /workspace
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mpl OPENBLAS_NUM_THREADS=2
