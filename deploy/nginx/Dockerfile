FROM nginx:1.30.6-alpine

COPY bootstrap.conf /etc/nginx/bootstrap.conf
COPY tls.conf /etc/nginx/tls.conf
COPY select-config.sh /docker-entrypoint.d/40-select-site-config.sh
RUN chmod 755 /docker-entrypoint.d/40-select-site-config.sh

EXPOSE 80 443
