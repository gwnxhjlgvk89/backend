"""Run bounded sequential synthetic journeys; no fixture data outside club_test."""
import os,json,subprocess,time,signal
from pathlib import Path
os.environ['CLUB_NATIVE_CAPACITY']='1'
base=['.venv/bin/python','scripts/load_distributed_journey.py','--url','https://wjy-1214.cloud','--ssh','ubuntu@43.142.19.144','--control','/tmp/club-full-target-ssh','--users','1500','--processes','3','--client-profile','connected_first','--rounds','1']
Path('reports/full-direct').mkdir(exist_ok=True)
os.environ.pop('PYTHONPATH',None);os.environ.pop('CLUB_VPC_DIAGNOSTIC',None)
cases=[(f'cold-{i}','login','uniform',45) for i in range(1,4)]+[(f'ready-{i}','ready','uniform',45) for i in range(1,4)]+[(f'hot-{i}','ready','hot_club',45) for i in range(1,4)]+[(f'last-{i}','ready','last_seat',45) for i in range(1,4)]+[('online-600','ready','uniform',600),('mixed','mixed','uniform',45),('reconnect','reconnect','uniform',45)]
cases.append(('first-password','login','uniform',45))
child=None

def stop(*args):
 if child and child.poll() is None:child.terminate()
 raise SystemExit('Stopped by operator')
signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
progress=[]
try:
 for name,mode,scenario,hold in cases:
  report='reports/full-direct/'+name+'.json'
  print('START '+name,flush=True)
  command=base+['--mode',mode,'--scenario',scenario,'--hold-seconds',str(hold),'--report',report]
  if name=='first-password':command=['.venv/bin/python','scripts/run_first_login_case.py','--url','https://wjy-1214.cloud','--ssh','ubuntu@43.142.19.144','--control','/tmp/club-full-target-ssh','--report',report]
  child=subprocess.Popen(command)
  code=child.wait(timeout=hold+300)
  d=json.loads(Path(report).read_text());r=d['runs'][-1] if d['runs'] else {}
  row={'case':name,'exit_code':code,'completed':r.get('completed_students'),'enrollments':r.get('db',{}).get('enrollments'),'data_consistent':r.get('data_consistency_pass'),'login_p95':r.get('stages',{}).get('login',{}).get('p95_s'),'enrollment_p95':r.get('stages',{}).get('enroll',{}).get('p95_s'),'ws_online':r.get('websocket',{}).get('open_at_end'),'gates':r.get('scope_gates')}
  progress.append(row);Path('reports/full-direct/suite-progress.json').write_text(json.dumps(progress,indent=2)+'\n');print('RESULT '+json.dumps(row),flush=True)
  if code or not r.get('data_consistency_pass'):raise SystemExit('Stop after orchestration or data consistency failure')
  time.sleep(5)
finally:
 if child and child.poll() is None:child.terminate();child.wait(timeout=30)
 cleanup=['ssh','-S','/tmp/club-full-target-ssh','-o','BatchMode=yes','ubuntu@43.142.19.144',"sudo systemctl stop club-full-direct2-observer.service; cd /srv/club/current && sudo .venv/bin/python deploy/run-private-env.py /etc/club/load-test.env .venv/bin/python /tmp/club-close-test-20260930.py"]
 with open('reports/full-direct/closed.json','w') as out:subprocess.run(cleanup,stdout=out,check=True,timeout=30)
