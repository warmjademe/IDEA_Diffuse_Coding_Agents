FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN sed -i 's|http://archive.ubuntu.com|http://cn.archive.ubuntu.com|g' /etc/apt/sources.list.d/ubuntu.sources \
    && apt-get update \
    && apt-get install -y --no-install-recommends openjdk-11-jdk-headless git subversion perl \
       curl unzip ca-certificates cpanminus make build-essential ant python3 \
       libdbd-csv-perl libdbi-perl libjson-perl libjson-parse-perl libstring-interpolate-perl \
       liburi-perl libperl-critic-perl tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV TZ=America/Los_Angeles
ENV PATH=/defects4j/framework/bin:/usr/lib/jvm/java-11-openjdk-amd64/bin:$PATH
WORKDIR /work
