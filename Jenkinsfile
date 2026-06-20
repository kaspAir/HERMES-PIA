// Methodos CI/CD-Pipeline
//
// Stages:
//   1. Regressionstests  – sauberer python:3.12-slim-Container
//   2. Deploy prod       – Branch 'main'  → hermespia.ch (Port 8000, Gunicorn)
//   3. Deploy test       – Branch 'test'  → hermespia.ch (Port 8001, Gunicorn)
//
// Voraussetzungen Jenkins:
//   - SSH-Credential 'hermespia-deploy' (privater Key für u7031y_kaspar@83.228.238.194)
//   - Docker + Docker-Pipeline-Plugin (nur für Testcontainer)
//
// Voraussetzungen Server hermespia.ch:
//   - Python-venv unter ~/venv, Methodos-Repo unter ~/methodos
//   - .env mit ANTHROPIC_API_KEY und FLASK_SECRET_KEY
//   - ~/bin/start-methodos.sh für Gunicorn-Start

pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 20, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        DEPLOY_HOST = 'u7031y_kaspar@83.228.238.194'
        APP_DIR     = '/home/clients/2a1849703150229016af3666c2f46b09/methodos'
        VENV        = '/home/clients/2a1849703150229016af3666c2f46b09/venv'
        REPO_URL    = 'https://github.com/kaspAir/Methodos'
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

        stage('Deploy prod') {
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} '
                            cd ${APP_DIR}
                            git fetch origin
                            git reset --hard origin/main
                            source ${VENV}/bin/activate
                            pip install -r requirements.txt -q
                            PID_FILE=\$HOME/tmp/gunicorn.pid
                            [ -f "\$PID_FILE" ] && kill \$(cat "\$PID_FILE") 2>/dev/null || true
                            sleep 1
                            set -a; source .env; set +a
                            nohup gunicorn run:app \\
                                --bind 127.0.0.1:8000 --workers 2 --timeout 120 \\
                                --access-logfile logs/access.log \\
                                --error-logfile logs/error.log > /dev/null 2>&1 &
                            echo \$! > \$HOME/tmp/gunicorn.pid
                            sleep 2 && curl -sf http://127.0.0.1:8000 > /dev/null && echo "OK: prod laeuft"
                        '
                    """
                }
            }
        }

        stage('Deploy test') {
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} '
                            if [ ! -d "\$HOME/methodos-test/.git" ]; then
                                git clone ${REPO_URL} \$HOME/methodos-test
                            fi
                            cd \$HOME/methodos-test
                            git fetch origin
                            git reset --hard origin/test
                            source ${VENV}/bin/activate
                            pip install -r requirements.txt -q
                            PID_FILE=\$HOME/tmp/gunicorn-test.pid
                            [ -f "\$PID_FILE" ] && kill \$(cat "\$PID_FILE") 2>/dev/null || true
                            sleep 1
                            set -a
                            source \$HOME/methodos/.env
                            DATABASE_URL=sqlite:///\$HOME/methodos-test/data/methodos-test.db
                            set +a
                            mkdir -p \$HOME/methodos-test/data \$HOME/methodos-test/logs
                            cd \$HOME/methodos-test
                            nohup gunicorn run:app \\
                                --bind 127.0.0.1:8001 --workers 1 --timeout 120 \\
                                --access-logfile logs/access.log \\
                                --error-logfile logs/error.log > /dev/null 2>&1 &
                            echo \$! > \$HOME/tmp/gunicorn-test.pid
                            sleep 2 && curl -sf http://127.0.0.1:8001 > /dev/null && echo "OK: test laeuft"
                        '
                    """
                }
            }
        }

    }

    post {
        success {
            echo "Pipeline gruen – deployed auf hermespia.ch."
        }
        failure {
            echo 'Pipeline rot – siehe Stage-Logs und Testbericht.'
        }
    }
}
