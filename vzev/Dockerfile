ARG BUILD_FROM
FROM $BUILD_FROM

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-pandas python3-openpyxl python3-yaml python3-reportlab \
       python3-matplotlib python3-flask python3-requests \
    && rm -rf /var/lib/apt/lists/*

ENV MPLCONFIGDIR=/tmp/matplotlib PYTHONUNBUFFERED=1

COPY app /app
COPY config.yaml /app/addon.yaml
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
