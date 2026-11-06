FROM python:3.12-slim
WORKDIR /app
COPY dz /app/dz
RUN useradd --uid 10001 --create-home runner && mkdir /state && chown runner /state
USER 10001
EXPOSE 8771
CMD ["python", "-m", "dz.platform.cli", "--root", "/state/tenants", "serve", "--host", "0.0.0.0", "--port", "8771"]
