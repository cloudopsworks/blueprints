# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#
ARG IMAGE_NAME=nginxinc/nginx-unprivileged:1.29-alpine

FROM $IMAGE_NAME AS base

ARG NGINX_ERROR_LOG_LEVEL=warn
ARG NGINX_ERROR_LOG_PATH="/var/log/nginx/error.log"
ARG NGINX_ACCESS_LOG_TYPE=json
ARG NGINX_ACCESS_LOG_PATH="/var/log/nginx/access.log"
ARG USER_ID=10001
ARG GROUP_ID=10001
ARG USER_NAME=webapp
ARG GROUP_NAME=webapp

ARG BUILD_DIR=./build/

## Stage 1: Create NGINX configuration
USER root
COPY ./nginx.conf /etc/nginx/nginx.conf
RUN sed -i 's|\[ERROR_LOG\]|'"${NGINX_ERROR_LOG_PATH} ${NGINX_ERROR_LOG_LEVEL}"'|g' /etc/nginx/nginx.conf
RUN if [[ "${NGINX_ACCESS_LOG_TYPE}" == "off" ]] ; \
    then \
        sed -i 's|\[ACCESS_LOG\]|'"${NGINX_ACCESS_LOG_TYPE}"'|g' /etc/nginx/nginx.conf ; \
    else \
        sed -i 's|\[ACCESS_LOG\]|'"${NGINX_ACCESS_LOG_PATH} ${NGINX_ACCESS_LOG_TYPE}"'|g' /etc/nginx/nginx.conf ; \
    fi
# Override rest of nginx configuration
COPY ./nginx-app.conf /etc/nginx/conf.d/default.conf
COPY $BUILD_DIR /usr/share/nginx/html/

# Stage 2: Customized configuation injection occurs at command line
FROM base AS customized
WORKDIR /app/webapp
#<DOCKER-INJECTION-POINT>

# Stage 3: Final image
FROM customized AS final

# Create the user and group use addgroup in cases OS supports elsewhere use groupadd
#RUN addgroup --gid $GROUP_ID --system $GROUP_NAME \
#    && adduser --uid $USER_ID --system --ingroup $GROUP_NAME --home /app/webapp $USER_NAME
#<USERGROUP-INJECTION-POINT>
RUN chown -R $USER_NAME:$GROUP_NAME /usr/share/nginx/html \
    && chown -R $USER_NAME:$GROUP_NAME /app/webapp/

COPY ./startup.sh /app/webapp/
RUN chmod +x /app/webapp/startup.sh

USER $USER_NAME

EXPOSE 8080
ENTRYPOINT ["/app/webapp/startup.sh"]
