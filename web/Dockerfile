FROM node:22-alpine
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
EXPOSE 3000
# 개발 단계: 핫 리로드. 데모 배포 때 build/start로 바꾼다.
CMD ["npm", "run", "dev"]
