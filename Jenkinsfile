// Methodos CI-Pipeline.
//
// Zwei Stages, beide Docker-getrieben:
//   1. Regressionstests in einem sauberen python:3.12-slim-Container.
//      Das Ergebnis wird als JUnit-XML veroeffentlicht, damit Jenkins den
//      Testverlauf grafisch zeigt (inkl. des Gap-Check-Showpieces).
//   2. Docker-Image bauen - laeuft NUR, wenn die Tests gruen sind, und ist
//      damit das Gate: was nicht testet, wird nicht gebaut.
//
// Voraussetzung: ein Jenkins-Agent mit Docker (Docker-Pipeline-Plugin +
// erreichbarer Docker-Daemon). Genau das "Docker-Agent"-Setup.

pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 20, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        IMAGE_NAME = 'methodos'
    }

    stages {
        stage('Regressionstests') {
            steps {
                script {
                    // -u root: pip darf im Container ins System-site-packages schreiben.
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
                    // reports/junit.xml liegt im gemounteten Workspace und ist
                    // damit auch nach Container-Ende fuer Jenkins lesbar.
                    junit 'reports/junit.xml'
                }
            }
        }

        stage('Docker-Image bauen') {
            steps {
                script {
                    // Baut das Dockerfile. Schlaegt der Build fehl, faellt die
                    // Pipeline rot - so faengst du kaputte Images vor dem Deploy.
                    def image = docker.build("${IMAGE_NAME}:${env.BUILD_NUMBER}")
                    // Zusaetzlich als :latest taggen (lokal im Daemon).
                    image.tag('latest')
                }
            }
        }
    }

    post {
        success {
            echo "OK - Tests gruen, Image ${IMAGE_NAME}:${env.BUILD_NUMBER} gebaut."
        }
        failure {
            echo 'Pipeline rot - siehe Stage-Logs und Testbericht.'
        }
    }
}
