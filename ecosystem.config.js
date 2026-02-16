module.exports = {
  apps: [{
    name: 'ims-server',
    script: '/root/fanxiaolongx-max/IMS/run.py',
    interpreter: '/root/fanxiaolongx-max/IMS/venv/bin/python',
    cwd: '/root/fanxiaolongx-max/IMS',
    env: {
      SERVER_IP: '113.44.149.111',
      NODE_ENV: 'production'
    },
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    error_file: '/root/.pm2/logs/ims-server-error.log',
    out_file: '/root/.pm2/logs/ims-server-out.log',
    merge_logs: true,
    autorestart: true,
    max_restarts: 5
  }]
}
