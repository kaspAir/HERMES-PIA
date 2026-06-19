// Methodos CI/CD-Pipeline
//
// Stages:
//   1. Regressionstests  – sauberer python:3.12-slim-Container
//   2. Docker-Image      – baut und taggt das Image (Gate: nur nach grünen Tests)
//   3. Deploy test       – nur auf Branch 'test'  → methodos-test  (Port 5001)
//   4. Deploy prod       – nur auf Branch 'main'  → methodos-prod  (Port 5000)
//
// Voraussetzungen auf dem Jenkins-Server:
//   - Docker + Docker-Pipeline-Plugin
//   - SSH-Credential 'phronesis-deploy' (privater Key für deploy@phronesis.swiss)
//   - Auf dem Zielserver: Docker, docker-compose, /opt/methodos/docker-compose.yml
//     und Secrets unter /opt/methodos/secrets/{prod,test}.env

pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 20, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        IMAGE_NAME   = 'methodos'
        DEPLOY_HOST  = 'deploy@phronesis.swiss'
        DEPLOY_PATH  = '/opt/methodos'
    }

    stages {

        stage('Regressionstests') {
            steps {
                script {
                    docker.image('python:3.12-slim').inside('-u root') {
                        sh '''
                            python --version
                            pip install --no-cache-dir -r tests/requirements.txt
                            pytest tests/regression -v --junitxml=reports/junit.xml
                        '''
                    }
                }
            }
            post {
                always {
                    junit 'reports/junit.xml'
                }
            }
        }

        stage('Docker-Image bauen') {
            steps {
                script {
                    def tag = env.BRANCH_NAME == 'main' ? 'prod' : 'test'
                    def image = docker.build("${IMAGE_NAME}:${tag}")
                    image.tag(env.BUILD_NUMBER)
                }
            }
        }

        stage('Deploy test') {
            when { branch 'test' }
            steps {
                sshagent(credentials: ['phronesis-deploy']) {
                    sh """
                        docker save ${IMAGE_NAME}:test | gzip | \
                            ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} \
                            'gunzip | docker load'

                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} \
                            'cd ${DEPLOY_PATH} && \
                             docker compose up -d --no-build methodos-test && \
                             docker compose ps methodos-test'
                    """
                }
            }
        }

        stage('Deploy prod') {
            when { branch 'main' }
            steps {
                sshagent(credentials: ['phronesis-deploy']) {
                    sh """
                        docker save ${IMAGE_NAME}:prod | gzip | \
                            ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} \
                            'gunzip | docker load'

                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} \
                            'cd ${DEPLOY_PATH} && \
                             docker compose up -d --no-build methodos-prod && \
                             docker compose ps methodos-prod'
                    """
                }
            }
        }

    }

    post {
        success {
            echo "OK – Tests grün, Image ${IMAGE_NAME}:${env.BUILD_NUMBER} gebaut und deployt."
        }
        failure {
            echo 'Pipeline rot – siehe Stage-Logs und Testbericht.'
        }
    }
}
