# (c) 2024 - Cloud Ops Works LLC - https://cloudops.works/
#            On GitHub: https://github.com/cloudopsworks
#            Distributed Under Apache v2.0 License
#
ARG IMAGE_NAME=node:18-alpine
ARG USER_ID=0
ARG GROUP_ID=0

FROM $IMAGE_NAME AS base

## Stage 1: Create NGINX configuration
USER root

# Copy the application configuarion as per the application
COPY . /app/webapp/

# Stage 2: Customized configuation injection occurs at command line
FROM base AS customized
WORKDIR /app
#<DOCKER-INJECTION-POINT>

# Stage 3: Final image
FROM customized AS final

RUN chown -R $USER_ID:$GROUP_ID /app/webapp/

COPY ./startup.sh /app/webapp/
RUN chmod +x /app/webapp/startup.sh

USER $USER_ID

