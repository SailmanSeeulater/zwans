# Included under [storage].
driver = s3
bucket = ingest-${env:DEPLOY_ENV:-dev}
tags = [ingest, raw]

[retention]
days = 30
