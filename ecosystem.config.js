const path = require('path');

module.exports = {
  apps: [{
    name: 'ims-server',
    script: path.join(__dirname, 'run.py'),
    interpreter: 'python3',
    cwd: __dirname,
    env: {
      SERVER_IP: 'AUTO_DETECT',
      NODE_ENV: 'production'
    },
    log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
    error_file: path.join(require('os').homedir(), '.pm2', 'logs', 'ims-server-error.log'),
    out_file: path.join(require('os').homedir(), '.pm2', 'logs', 'ims-server-out.log'),
    merge_logs: true,
    autorestart: true,
    max_restarts: 5
  }]
}
