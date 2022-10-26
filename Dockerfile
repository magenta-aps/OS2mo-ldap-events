FROM python:3.10

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1
RUN pip install --no-cache-dir poetry==1.2.0 tomlkit

WORKDIR /opt
COPY poetry.lock pyproject.toml ./
RUN poetry install --no-dev

COPY mo_ldap_events /opt/app/mo_ldap_events
WORKDIR /opt/app

CMD ["poetry", "run", "python", "-m", "mo_ldap_events.ldap"]

# Add build version to the environment last to avoid build cache misses
ARG COMMIT_TAG
ARG COMMIT_SHA
ENV COMMIT_TAG=${COMMIT_TAG:-HEAD} \
    COMMIT_SHA=${COMMIT_SHA}
