// HERMES PIA CI/CD-Pipeline
//
// Stages pro Pipeline-Job:
//   hermes-pia develop     → Tests + Deploy dev   (origin/develop     → Port 8003, dev.hermespia.ch)
//   hermes-pia test        → Tests + Deploy test  (origin/test        → Port 8001, test.hermespia.ch)
//   hermes-pia integration → Tests + Deploy int   (origin/integration → Port 8002, int.hermespia.ch)
//   hermes-pia main        → Tests + Deploy prod  (origin/main        → Port 8000, hermespia.ch)
//
// ACHTUNG Promotion: test.hermespia.ch ist KUNDEN-Umgebung (LLV-Accounts).
// Nach test wird nur noch auf ausdrueckliche Freigabe promotet; die laufende
// Entwicklung landet ueber develop automatisch auf dev.hermespia.ch.
//
// Betrieb & Stabilitaet:
//   Deploy und (Neu-)Start laufen ueber EIN Skript: deploy/hermes_ctl.sh
//   (per SSH-stdin ausgefuehrt). Es installiert sich beim Deploy nach
//   ~/bin/hermes/ und richtet einen CRON-WATCHDOG ein, der alle 2 Minuten
//   /health prueft und eine abgestuerzte Umgebung automatisch neu startet –
//   damit ist kein manueller Rebuild mehr noetig, wenn ein Prozess stirbt.
//   Prozess-Kill bleibt PID-verifiziert (nie blind, nie `pkill -f`).
//
// Voraussetzungen Jenkins:
//   - SSH-Credential 'hermespia-deploy' (privater Key für u7031y_kaspar@83.228.238.194)
//   - Docker + Docker-Pipeline-Plugin (für Testcontainer)
//
// Voraussetzungen Server hermespia.ch:
//   - Python-venv unter ~/venv, Prod-Repo unter ~/methodos
//   - ~/methodos/.env mit ANTHROPIC_API_KEY, FLASK_SECRET_KEY (geteilt)
//   - cron verfuegbar (Watchdog); curl + fuser vorhanden

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

        // Deploy: das Steuerskript wird per stdin auf den Server gepiped und dort
        // ausgefuehrt (env, Repo, venv als Argumente). Es macht git-Reset, pip,
        // installiert den Cron-Watchdog und startet die Umgebung PID-sicher.

        stage('Deploy prod') {
            when { expression { env.JOB_NAME.contains('main') } }
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh "ssh -T -o StrictHostKeyChecking=no ${DEPLOY_HOST} bash -s deploy prod ${REPO_URL} ${VENV} < deploy/hermes_ctl.sh"
                }
            }
        }

        stage('Deploy int') {
            when { expression { env.JOB_NAME.contains('integration') } }
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh "ssh -T -o StrictHostKeyChecking=no ${DEPLOY_HOST} bash -s deploy int ${REPO_URL} ${VENV} < deploy/hermes_ctl.sh"
                }
            }
        }

        stage('Deploy test') {
            when { expression { env.JOB_NAME.contains('test') } }
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh "ssh -T -o StrictHostKeyChecking=no ${DEPLOY_HOST} bash -s deploy test ${REPO_URL} ${VENV} < deploy/hermes_ctl.sh"
                }
            }
        }

        stage('Deploy dev') {
            when { expression { env.JOB_NAME.contains('develop') } }
            steps {
                sshagent(credentials: ['hermespia-deploy']) {
                    sh "ssh -T -o StrictHostKeyChecking=no ${DEPLOY_HOST} bash -s deploy dev ${REPO_URL} ${VENV} < deploy/hermes_ctl.sh"
                }
            }
        }

        // Schwere fachliche E2E-Faelle gegen ECHTE Dienste (STT+LLM) – nur auf
        // Promotion (test/int/main), NICHT auf dev (Testkonzept §9). Bewusst
        // NICHT-BLOCKIEREND (catchError -> UNSTABLE): darf die Kunden-Promotion
        // nie rot faerben. Skip-sicher: ohne Aufnahme/Keys ueberspringt pytest.
        // Die Aufnahme liegt PRIVAT auf dem Agent (nie im oeffentlichen Repo),
        // Pfad via E2E_FIXTURES_DIR; Keys (ANTHROPIC_API_KEY, STT_API_KEY) aus der
        // Jenkins-Umgebung. Aktiviert sich, sobald beides vorhanden ist.
        stage('E2E fachlich (Promotion)') {
            when {
                expression {
                    env.JOB_NAME.contains('test') || env.JOB_NAME.contains('integration') ||
                    env.JOB_NAME.contains('main')
                }
            }
            steps {
                catchError(buildResult: 'SUCCESS', stageResult: 'UNSTABLE') {
                    script {
                        docker.image('python:3.12-slim').inside('-u root') {
                            sh '''
                                pip install --no-cache-dir -r tests/requirements.txt
                                export E2E_FIXTURES_DIR="${E2E_FIXTURES_DIR:-/var/jenkins_home/e2e-fixtures}"
                                pytest tests/e2e -m promotion -v --junitxml=reports/e2e-junit.xml
                            '''
                        }
                    }
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'reports/e2e-junit.xml'
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
