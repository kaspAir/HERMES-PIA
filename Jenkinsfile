// HERMES PIA CI/CD-Pipeline
//
// Stages pro Pipeline-Job:
//   hermes-pia develop     → nur Regressionstests (kein Deploy)
//   hermes-pia test        → Tests + Deploy test  (origin/test        → Port 8001, test.hermespia.ch)
//   hermes-pia integration → Tests + Deploy int   (origin/integration → Port 8002, int.hermespia.ch)
//   hermes-pia main        → Tests + Deploy prod  (origin/main        → Port 8000, hermespia.ch)
//
// Voraussetzungen Jenkins:
//   - SSH-Credential 'hermespia-deploy' (privater Key für u7031y_kaspar@83.228.238.194)
//   - Docker + Docker-Pipeline-Plugin (für Testcontainer)
//
// Voraussetzungen Server hermespia.ch:
//   - Python-venv unter ~/venv, Methodos-Repo unter ~/methodos
//   - .env mit ANTHROPIC_API_KEY und FLASK_SECRET_KEY

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
        REPO_URL    = 'https://github.com/kaspAir/HERMES-PIA'
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
            when {
                expression { env.JOB_NAME.contains('main') }
            }
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} '
                            cd ${APP_DIR}
                            git remote set-url origin ${REPO_URL}
                            git fetch origin
                            git reset --hard origin/main
                            source ${VENV}/bin/activate
                            pip install -r requirements.txt -q
                            PID_FILE=\$HOME/tmp/gunicorn.pid
                            [ -f "\$PID_FILE" ] && kill \$(cat "\$PID_FILE") 2>/dev/null || true
                            pkill -f "gunicorn.*:8000" 2>/dev/null || true
                            for i in \$(seq 1 20); do pgrep -f "gunicorn.*:8000" >/dev/null || break; sleep 1; done
                            pkill -9 -f "gunicorn.*:8000" 2>/dev/null || true
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

        stage('Deploy int') {
            when {
                expression { env.JOB_NAME.contains('integration') }
            }
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} '
                            if [ ! -d "\$HOME/methodos-int/.git" ]; then
                                git clone ${REPO_URL} \$HOME/methodos-int
                            fi
                            cd \$HOME/methodos-int
                            git remote set-url origin ${REPO_URL}
                            git fetch origin
                            git reset --hard origin/integration
                            source ${VENV}/bin/activate
                            pip install -r requirements.txt -q
                            PID_FILE=\$HOME/tmp/gunicorn-int.pid
                            [ -f "\$PID_FILE" ] && kill \$(cat "\$PID_FILE") 2>/dev/null || true
                            pkill -f "gunicorn.*:8002" 2>/dev/null || true
                            for i in \$(seq 1 20); do pgrep -f "gunicorn.*:8002" >/dev/null || break; sleep 1; done
                            pkill -9 -f "gunicorn.*:8002" 2>/dev/null || true
                            sleep 1
                            set -a
                            source \$HOME/methodos/.env
                            DATABASE_URL=sqlite:///\$HOME/methodos-int/data/methodos-int.db
                            set +a
                            mkdir -p \$HOME/methodos-int/data \$HOME/methodos-int/logs
                            cd \$HOME/methodos-int
                            nohup gunicorn run:app \\
                                --bind 127.0.0.1:8002 --workers 1 --timeout 120 \\
                                --access-logfile logs/access.log \\
                                --error-logfile logs/error.log > /dev/null 2>&1 &
                            echo \$! > \$HOME/tmp/gunicorn-int.pid
                            sleep 2 && curl -sf http://127.0.0.1:8002 > /dev/null && echo "OK: int laeuft"
                        '
                    """
                }
            }
        }

        stage('Deploy test') {
            when {
                expression { env.JOB_NAME.contains('test') }
            }
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} '
                            if [ ! -d "\$HOME/methodos-test/.git" ]; then
                                git clone ${REPO_URL} \$HOME/methodos-test
                            fi
                            cd \$HOME/methodos-test
                            git remote set-url origin ${REPO_URL}
                            git fetch origin
                            git reset --hard origin/test
                            source ${VENV}/bin/activate
                            pip install -r requirements.txt -q
                            PID_FILE=\$HOME/tmp/gunicorn-test.pid
                            [ -f "\$PID_FILE" ] && kill \$(cat "\$PID_FILE") 2>/dev/null || true
                            pkill -f "gunicorn.*:8001" 2>/dev/null || true
                            for i in \$(seq 1 20); do pgrep -f "gunicorn.*:8001" >/dev/null || break; sleep 1; done
                            pkill -9 -f "gunicorn.*:8001" 2>/dev/null || true
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
