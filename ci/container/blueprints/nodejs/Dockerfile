# (c) 2024 - Cloud Ops Works LLC - https://cloudops.works/
#            On GitHub: https://github.com/cloudopsworks
#            Distributed Under Apache v2.0 License
#
ARG IMAGE_NAME=node:22-alpine

FROM $IMAGE_NAME AS base

ARG NODE_OPTS=""
ARG APM_OPTS=""

ARG USER_ID=10001
ARG GROUP_ID=10001
ARG USER_NAME=webapp
ARG GROUP_NAME=webapp

## Stage 1: Create NGINX configuration
USER root

# Copy the application configuarion as per the application
COPY . /app/webapp/
#<NODE-INJECTION-POINT>

# Stage 2: Customized configuation injection occurs at command line
FROM base AS customized
WORKDIR /app
#<DOCKER-INJECTION-POINT>

# Stage 3: Final image
FROM customized AS final

# Create the user and group use addgroup in cases OS supports elsewhere use groupadd
#RUN addgroup --gid $GROUP_ID --system $GROUP_NAME \
#    && adduser --uid $USER_ID --system --ingroup $GROUP_NAME --home /app/webapp $USER_NAME
#<USERGROUP-INJECTION-POINT>
# Run chown regardess of the previous step
RUN chown -R $USER_NAME:$GROUP_NAME /app/webapp/

COPY ./startup.sh /app/webapp/
RUN chmod +x /app/webapp/startup.sh
ENV NODE_OPTS=${NODE_OPTS}
ENV APM_OPTS=${APM_OPTS}

USER $USER_NAME

EXPOSE 8080
ENTRYPOINT ["/app/webapp/startup.sh"]
