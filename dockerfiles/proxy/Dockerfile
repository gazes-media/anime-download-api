FROM node:18.16.0-alpine3.17
WORKDIR /app
ARG VERSION=11b306ca87a4612987a4b3529f814fe5e5053455
RUN wget -O proxy.zip "https://github.com/Deril-fr/proxy/archive/$VERSION.zip" && \
    unzip proxy.zip &&\
    rm proxy.zip &&\
    cp -a proxy-$VERSION/. . &&\
    rm -r proxy-$VERSION &&\
    npm ci
CMD ["node", "./main.js"]
