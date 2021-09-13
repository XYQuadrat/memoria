FROM python:3.9.7-alpine3.14

RUN /usr/sbin/adduser -g python -D python

USER python
RUN /usr/local/bin/python -m venv /home/python/venv

COPY --chown=python:python requirements.txt /home/python/memoriae/requirements.txt
RUN /home/python/venv/bin/pip install --no-cache-dir --requirement /home/python/memoriae/requirements.txt

ENV PATH="/home/python/venv/bin:${PATH}" \
    PYTHONUNBUFFERED="1" \
    QUIZ_SERVER_URL="This is set by env var QUIZ_SERVER_URL" \
    TZ="Etc/UTC"

WORKDIR /home/python/memoriae
ENTRYPOINT ["/home/python/venv/bin/python"]
CMD ["-m", "memoriae"]

LABEL org.opencontainers.image.source="https://github.com/williamjacksn/memoriae"

COPY --chown=python:python memoriae /home/python/memoriae/memoriae
