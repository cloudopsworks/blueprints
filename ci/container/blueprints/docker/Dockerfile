# (c) 2021-2025
#     Cloud Ops Works LLC - https://cloudops.works/
#     Find us on:
#       GitHub: https://github.com/cloudopsworks
#       WebSite: https://cloudops.works
#     Distributed Under Apache v2.0 License
#
ARG IMAGE_NAME=node:20-alpine

FROM $IMAGE_NAME AS base

ARG USER_ID=10001
ARG GROUP_ID=10001
ARG USER_NAME=webapp
ARG GROUP_NAME=webapp

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

# Create the user and group use addgroup in cases OS supports elsewhere use groupadd - defaults for alpine images
#RUN addgroup --gid $GROUP_ID --system $GROUP_NAME \
#    && adduser --uid $USER_ID --system --ingroup $GROUP_NAME --home /app/webapp $USER_NAME
#<USERGROUP-INJECTION-POINT>
# Run chown regardess of the previous step
RUN chown -R $USER_NAME:$GROUP_NAME /app/webapp/

COPY ./startup.sh /app/webapp/
RUN chmod +x /app/webapp/startup.sh

USER $USER_NAME

