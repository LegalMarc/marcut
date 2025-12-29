import json,hashlib,time

def sha256_file(p):
 h=hashlib.sha256();
 with open(p,'rb') as f:
  for ch in iter(lambda:f.read(8192),b''):
   h.update(ch)
 return h.hexdigest()

def write_report(report_path,input_path,model,spans):
 data={'created_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'input_sha256':sha256_file(input_path),'model':model,'spans':spans}
 with open(report_path,'w',encoding='utf-8') as f:
  f.write(json.dumps(data,indent=2))
