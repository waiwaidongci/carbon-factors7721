import {request} from './client.js';
export const loadAll=async()=>Object.fromEntries(await Promise.all(['sources','periods','policies','runs','schedules','deliveries','audits','declarations'].map(async k=>[k,await request('/'+k)])));
export const saveSource=(data,id)=>request('/sources'+(id?'/'+id:''),id?'PUT':'POST',{data});
export const savePolicy=data=>request('/policies','POST',{data});
export const submitRun=data=>request('/runs','POST',data);
export const approveRun=(id,note)=>request('/runs/'+id+'/approve','POST',{note});
export const tabulateDeclaration=run_id=>request('/declarations/tabulate','POST',{run_id});
export const confirmDeclaration=(draft_id,note='')=>request('/declarations/'+draft_id+'/confirm','POST',{note});
export const runDeclaration=run_id=>request('/runs/'+run_id+'/declaration');
