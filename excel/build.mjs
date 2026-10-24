import fs from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
import { buildSectorComparison } from './sector_comparison.mjs';
import { buildPeerValuation } from './peer_valuation.mjs';

const args=process.argv.slice(2), option=k=>args[args.indexOf(k)+1];
const input=JSON.parse(await fs.readFile(option('--input'),'utf8'));
const out=option('--out'); await fs.mkdir(out,{recursive:true});
const wb=Workbook.create();
const nativeLinks=[];
const nativeLink=(sheet,cell,url,label)=>{sheets[sheet].getRange(cell).values=[[label]];nativeLinks.push({sheet,cell,url});};
const names=['Dashboard','Assumptions','Bear','Base','Bull','Multiple policy','Peers','Transactions','Segments','NAV','Financials','Market','Methods','Drivers','Checks','Sources','Guide'];
if(input.research_notes?.length)names.splice(5,0,'Research');
if(input.historical_statements?.periods?.length)names.splice(1,0,'Statement history');
if(input.sector_comparison?.rows?.length>1)names.splice(1,0,'Sector comparison');
if(input.peer_valuation)names.splice(1,0,'Peer valuation');
const sheets=Object.fromEntries(names.map(n=>[n,wb.worksheets.add(n)]));
const ink='#172F48', teal='#12695C', blue='#0000FF', green='#008000', light='#EDF3F6', amber='#FFF1CD';
const amount='#,##0;(#,##0);"-"', pct='0.0%;(0.0%);"-"', price='"₹"#,##0.00;("₹"#,##0.00);"-"';
const col=i=>{let text='';for(let n=i+1;n>0;n=Math.floor((n-1)/26))text=String.fromCharCode(65+(n-1)%26)+text;return text;};
const put=(s,a,v)=>sheets[s].getRange(a).values=[[v]];
const form=(s,a,v)=>{sheets[s].getRange(a).formulas=[[v]];sheets[s].getRange(a).format.font.color=names.indexOf(s)<1?ink:v.includes('!')?green:'#000000';};
const block=(s,a,v)=>sheets[s].getRange(a).write(v);
const title=(s,t,sub)=>{put(s,'C2',t);sheets[s].getRange('C2:O2').format={fill:ink,font:{color:'#FFFFFF',bold:true,size:15},rowHeight:30};if(sub)put(s,'C3',sub);};
const band=(s,r,t,end='I')=>{put(s,`C${r}`,t);sheets[s].getRange(`C${r}:${end}${r}`).format={fill:light,font:{bold:true,color:ink},rowHeight:25};};
const inputCell=(s,a,v=null)=>{if(v!==null&&v!==undefined)put(s,a,v);sheets[s].getRange(a).format={fill:amber,font:{color:blue}};};
const link=(s,a,ref)=>form(s,a,`=IF(ISNUMBER(${ref}),${ref},"n.a.")`);
const ready=(refs,body,extra='TRUE')=>`=IF(IFERROR(COUNT(${refs.join(',')})=${refs.length},FALSE),IF(${extra},${body},"n.a."),"n.a.")`;
for(const [name,s] of Object.entries(sheets)){
 s.showGridLines=false;s.tabColor=['Dashboard','Assumptions'].includes(name)?teal:ink;
 s.getRange('A1:AO240').format={font:{name:'Arial',size:10,color:ink},rowHeight:20,verticalAlignment:'center'};
 s.getRange('A:B').format.columnWidth=2.5;s.getRange('C:C').format.columnWidth=43;
 s.getRange('D:AO').format.columnWidth=17;s.getRange('D5:AO240').setNumberFormat(amount);
 if(!['Dashboard','Guide'].includes(name))s.freezePanes.freezeRows(5);
}

// Original actuals remain separate from all scenario builds.
const financialPeriods=input.periods.map((date,index)=>({date,index})).filter(p=>p.date);
const displayedPeriods=financialPeriods.length?financialPeriods:[{date:null,index:4}];
const financialColumn=index=>col(4+displayedPeriods.findIndex(p=>p.index===index));
const latestFinancialColumn=col(3+displayedPeriods.length);
const actualDate=`'Financials'!${latestFinancialColumn}6`;
title('Financials','Comparable forecast inputs','Plain INR and actual shares. Full reported history is on Statement history.');
block('Financials','C5',[['Metric','Unit',...displayedPeriods.map(p=>p.date?`FY${p.date.slice(0,4)}`:'No reviewed period')]]);
put('Financials','C6','Period ended');
for(const p of displayedPeriods)if(p.date)put('Financials',`${financialColumn(p.index)}6`,new Date(p.date+'T00:00:00Z'));
sheets.Financials.getRange(`E6:${latestFinancialColumn}6`).setNumberFormat('dd-mmm-yyyy');
sheets.Financials.getRange(`E:${latestFinancialColumn}`).format.columnWidth=24;
const metricRows={};
Object.keys(input.financials).forEach((metric,i)=>{let r=7+i;metricRows[metric]=r;put('Financials',`C${r}`,metric.replaceAll('_',' '));put('Financials',`D${r}`,metric==='shares'?'actual shares':'INR');
 for(const p of displayedPeriods){const v=input.financials[metric][p.index],cell=`${financialColumn(p.index)}${r}`;
  if(v===null||v===undefined){put('Financials',cell,'Not verified');sheets.Financials.getRange(cell).format={fill:'#F4F6F7',font:{color:'#536672'}};}
  else inputCell('Financials',cell,v);
 }});
const actual=m=>`'Financials'!${latestFinancialColumn}${metricRows[m]}`;
const historyScopes=[...new Set((input.historical_statements?.periods||[]).map(p=>p.scope))];
const forecastBasis=(input.historical_statements?.periods||[]).find(p=>p.end===displayedPeriods.at(-1).date)?.scope;
const inputNotes=[`Forecast basis: ${forecastBasis||'reviewed matching reporting scope'}. Only available periods on this basis are shown.`,
 historyScopes.length>1?'Older periods on a different reporting basis are preserved on Statement history. A business disposal or demerger can change comparability. Do not combine these as like-for-like growth.':'Statement history contains the full reviewed history and source audit.',
 'Not verified means no accepted historical input. Forecast assumptions remain separate on Assumptions. Missing capex is not zero.'];
inputNotes.forEach((text,i)=>{const r=30+i*3;put('Financials',`C${r}`,text);sheets.Financials.getRange(`C${r}:I${r+2}`).merge();sheets.Financials.getRange(`C${r}:I${r+2}`).format.wrapText=true;});

// Preserve as-reported statements on their own dated basis. Only the matched
// Financials schedule feeds forecasts; a demerged or 15-month series cannot
// silently become a comparable forecast calibration series.
if(sheets['Statement history']){
 const s='Statement history',h=input.historical_statements,hr={};
 title(s,'Financial statement history','₹ crore except actual shares. As-reported periods; compare scopes before drawing growth conclusions.');
 put(s,'C5','Reported measure');put(s,'C6','Reporting dates');put(s,'C7','Reporting basis');put(s,'C8','Days in reporting period');
 h.periods.forEach((p,i)=>{const c=col(3+i);put(s,`${c}5`,p.label);put(s,`${c}6`,`${p.start} to ${p.end}`);put(s,`${c}7`,p.scope);put(s,`${c}8`,p.duration_days);});
 sheets[s].getRange('D:O').format.columnWidth=29;
 sheets[s].getRange('D5:O8').format.wrapText=true;sheets[s].getRange('C6:O7').format.rowHeight=42;
 h.metrics.forEach((m,i)=>{const r=10+i;hr[m.id]=r;put(s,`C${r}`,m.label+(m.id==='shares'?' (actual)':''));h.periods.forEach((p,y)=>{const c=col(3+y),v=p.values[m.id];put(s,`${c}${r}`,typeof v==='number'?(m.id==='shares'?v:v/10000000):'n.a.');sheets[s].getRange(`${c}${r}`).format.font.color=green;});});
 band(s,28,'Historical diagnostics');
 for(const [r,label] of [[29,'Attributable net margin'],[30,'Operating cash flow / parent PAT'],[31,'Operating cash flow less capex (₹ cr)'],[32,'Revenue growth (matched period only)']])put(s,`C${r}`,label);
 h.periods.forEach((p,y)=>{const c=col(3+y),rev=`${c}${hr.revenue}`,pat=`${c}${hr.net_income}`,cfo=`${c}${hr.cfo}`,capex=`${c}${hr.capex}`;
  put(s,'C33','Operating EBITDA margin');form(s,`${c}33`,ready([`${c}${hr.ebitda}`,rev],`${c}${hr.ebitda}/${rev}`,`${rev}>0`));
  form(s,`${c}29`,ready([pat,rev],`${pat}/${rev}`,`${rev}>0`));
  form(s,`${c}30`,ready([cfo,pat],`${cfo}/${pat}`,`${pat}>0`));
  form(s,`${c}31`,ready([cfo,capex],`${cfo}-${capex}`));
  const prev=h.periods[y-1],prior=col(2+y),span=prev?(Date.parse(p.end)-Date.parse(prev.end))/86400000:0;
  const comparable=prev&&p.scope===prev.scope&&Math.abs(p.duration_days-prev.duration_days)<=2&&span>=360&&span<=370;
  if(comparable)form(s,`${c}32`,ready([rev,`${prior}${hr.revenue}`],`${rev}/${prior}${hr.revenue}-1`,`${prior}${hr.revenue}>0`));else put(s,`${c}32`,'Not comparable');
 });
 sheets[s].getRange('D10:O26').setNumberFormat('#,##0.0;(#,##0.0);"-"');
 sheets[s].getRange(`D${hr.shares}:O${hr.shares}`).setNumberFormat(amount);
 sheets[s].getRange('D33:O33').setNumberFormat(pct);sheets[s].getRange('D10:O33').format.horizontalAlignment='right';
 sheets[s].getRange('D29:O29').setNumberFormat(pct);sheets[s].getRange('D30:O30').setNumberFormat('0.00"x"');sheets[s].getRange('D32:O32').setNumberFormat(pct);
 const notes=[h.qualification,h.investor_use,'Cash flow less capex is a historical cash measure, not FCFF. CFO is group cash flow; PAT is attributable to parent shareholders. Compare with NCI and exceptional items.',
  'HUL/ITC pre-demerger total operations are separated from current continuing operations. Nestlé 2023–24 is 15 months; standalone history is separated from consolidated years. Same scope does not establish organic growth.',...h.issues];
 notes.forEach((n,i)=>{const r=35+i*3;put(s,`C${r}`,n);sheets[s].getRange(`C${r}:H${r+2}`).merge();sheets[s].getRange(`C${r}:H${r+2}`).format.wrapText=true;});
 const start=36+notes.length*3;band(s,start,'Statement source audit');block(s,`C${start+1}`,[['Measure / period','Original file','PDF pages','Definition / comparability','Archived source']]);
 let r=start+2;h.periods.forEach(p=>h.metrics.forEach(m=>(p.sources[m.id]||[]).forEach(ref=>{block(s,`C${r}`,[[`${m.label} / ${p.label}`,ref.file,ref.pages,ref.definition,ref.url?'http://127.0.0.1:8000'+ref.url:'Source file in local library']]);sheets[s].getRange(`C${r}:G${r}`).format.wrapText=true;sheets[s].getRange(`C${r}:G${r}`).format.rowHeight=90;r++;})));
}

title('Market','Market and capital structure','Use matching observation dates, currency and lease treatment. Missing is not zero.');
const marketFields=['price_date','price','current_shares','debt','cash','nci','preferred','nonoperating_assets','quote_source','shares_date','balance_date','accounting_scope','lease_policy','currency','diluted_shares'];
const mr={}; marketFields.forEach((key,i)=>{const r=6+i;mr[key]=r;put('Market',`C${r}`,key.replaceAll('_',' '));const v=input.market[key];inputCell('Market',`D${r}`,v&&key.endsWith('_date')?new Date(v+'T00:00:00Z'):v);});
for(const field of ['price_date','shares_date','balance_date'])sheets.Market.getRange(`D${mr[field]}`).setNumberFormat('dd-mmm-yyyy');
form('Market','D23',ready(['D7','D8'],'D7*D8','AND(D7>0,D8>0)'));
put('Market','C23','Market equity value');put('Market','C24','Enterprise value');
form('Market','D24',ready(['D23','D9','D10','D11','D12','D29'],'D23+D9+D11+D12+D29-D10'));
put('Market','C25','Enterprise to equity adjustment');
form('Market','D25',ready(['D9','D10','D11','D12','D13','D29'],'D10+D13-D9-D11-D12-D29','AND(D17<>"",D18<>"",D19="INR")'));
put('Market','C22','Valuation date');inputCell('Market','D22',input.market.valuation_date?new Date(input.market.valuation_date+'T00:00:00Z'):null);sheets.Market.getRange('D22').setNumberFormat('dd-mmm-yyyy');
put('Market','C28','Assumed distributions / dividend claims');inputCell('Market','D28',input.market.interim_dividends);
put('Market','C29','Other debt-like claims');inputCell('Market','D29',input.market.other_senior_claims??0);
sheets.Market.getRange('D7').setNumberFormat(price);
put('Market','C30','Bridge and timing assumptions');
(input.market_notes||[]).forEach((note,i)=>{put('Market',`C${32+i*2}`,note);sheets.Market.getRange(`C${32+i*2}:K${33+i*2}`).merge();sheets.Market.getRange(`C${32+i*2}:K${33+i*2}`).format.wrapText=true;});

title('Assumptions','Assumptions and source register','Blue cells are editable. Blank estimates have no default value. All three cases calculate live.');
block('Assumptions','C5',[['Driver','Case','Source type','Source','Source date','Confidence','Rationale','Unit','Year 1','Year 2','Year 3','Year 4','Year 5','Documentation']]);
sheets.Assumptions.getRange('F:F').format.columnWidth=30;sheets.Assumptions.getRange('I:I').format.columnWidth=48;
const ar={};const definitions=Object.entries(input.driver_definitions);
for(let d=0;d<definitions.length;d++){
 const [id,[label,unit,group]]=definitions[d];ar[id]={};
 for(let c=0;c<3;c++){
  const r=6+d*4+c,scenario=['bear','base','bull'][c];ar[id][scenario]=r;
  const record=input.assumptions.find(a=>a.driver===id&&a.scenario===scenario);
  block('Assumptions',`C${r}`,[[label,scenario,record?.source_type??'',record?.source??'',record?.source_date?new Date(record.source_date+'T00:00:00Z'):null,record?.confidence??'unassessed',record?.rationale??'',unit,...(record?.values.map(v=>v===null?null:Number(v))??[null,null,null,null,null])]]);
  sheets.Assumptions.getRange(`E${r}:O${r}`).format.font.color=blue;
  sheets.Assumptions.getRange(`K${r}:O${r}`).format.fill=amber;
  if(unit==='fraction')sheets.Assumptions.getRange(`K${r}:O${r}`).setNumberFormat(pct);
  form('Assumptions',`P${r}`,`=IF(AND(E${r}<>"",F${r}<>"",ISNUMBER(G${r}),I${r}<>"",COUNT(K${r}:O${r})>0),"Documented","Missing evidence or estimates")`);
 }
}
sheets.Assumptions.getRange('G6:G240').setNumberFormat('dd-mmm-yyyy');
sheets.Assumptions.getRange('E6:E240').dataValidation={rule:{type:'list',values:['historical','external','management_guidance','analyst_assumption']}};
const driver=(id,scenario,y=0)=>`IF(AND('Assumptions'!P${ar[id][scenario]}="Documented",ISNUMBER('Assumptions'!${col(10+y)}${ar[id][scenario]})),'Assumptions'!${col(10+y)}${ar[id][scenario]},"n.a.")`;

title('Drivers','Company operating drivers','Choose a route only after reviewing the company disclosures.');
put('Drivers','C6','Revenue model');inputCell('Drivers','E6',input.revenue_route);
put('Drivers','C7','Profitability model');inputCell('Drivers','E7',input.margin_route);
sheets.Drivers.getRange('E6').dataValidation={rule:{type:'list',values:['Volume and price/mix','Direct disclosed drivers']}};
sheets.Drivers.getRange('E7').dataValidation={rule:{type:'list',values:['Cost bridge','EBITDA margin']}};
put('Drivers','C10','Exact growth relationship');put('Drivers','E10','(1 + volume growth) * (1 + price/mix growth) - 1');
put('Drivers','C12','Direct growth rationale');inputCell('Drivers','E12',input.direct_growth_rationale);
put('Drivers','C14','Disclosed driver');put('Drivers','F14','Source evidence');
input.drivers.forEach((d,i)=>block('Drivers',`C${15+i}`,[[d.driver,d.source_type,d.confidence,d.source]]));
if(input.drivers.length){sheets.Drivers.getRange('D:D').format.columnWidth=26;sheets.Drivers.getRange('F:F').format.columnWidth=82;sheets.Drivers.getRange(`C15:F${14+input.drivers.length}`).format.wrapText=true;sheets.Drivers.getRange(`C15:F${14+input.drivers.length}`).format.rowHeight=38;}

buildSectorComparison(input,{sheets,title,block,put,form,ready,nativeLink,ink,blue,pct});
buildPeerValuation(input,{sheets,title,block,put,form,ready,nativeLink,ink,blue,pct});

// Peer normalization and matching-period exclusions are visible to the analyst.
title('Peers','Comparable company analysis','Include only reviewed comparable observations with a consistent valuation date and financial period.');
const ph=['Company','Include','Rationale','Price','Shares','Debt','Cash','NCI','Preferred','Revenue','EBITDA','EBIT','Attributable PAT','Forward revenue','Forward EBITDA','Forward PAT','Invested capital','NOPAT','Source','Price date','Financial period','Review'];
block('Peers','C5',[ph]);
for(let r=6;r<=20;r++){
 inputCell('Peers',`C${r}`);sheets.Peers.getRange(`D${r}:X${r}`).format.fill=amber;
 form('Peers',`Y${r}`,ready([`F${r}`,`G${r}`],`F${r}*G${r}`,`AND(D${r}="Yes",E${r}<>"",U${r}<>"",ISNUMBER(V${r}),ISNUMBER(W${r}),X${r}="Reviewed",'Market'!D6=V${r})`));
 form('Peers',`Z${r}`,ready([`Y${r}`,`H${r}`,`I${r}`,`J${r}`,`K${r}`],`Y${r}+H${r}+J${r}+K${r}-I${r}`));
}
// Columns beyond Z use explicit names.
block('Peers','Y5',[['Market cap','Enterprise value','Forward P/E','Forward EV/EBITDA','EV/EBIT','Forward EV/Sales','Forward P/S']]);
// col() above is deliberately only used for A:Z; set these formula columns explicitly.
put('Peers','AF5','Forward EBIT');
for(let r=6;r<=20;r++){inputCell('Peers',`AF${r}`);for(const [c,num,den] of [['AA','Y','R'],['AB','Z','Q'],['AC','Z','AF'],['AD','Z','P'],['AE','Y','P']])form('Peers',`${c}${r}`,ready([`${num}${r}`,`${den}${r}`],`${num}${r}/${den}${r}`,`${den}${r}>0`));}
block('Peers','C25',[['Metric','Minimum','Maximum','Mean','Median','25th percentile','75th percentile','Included count']]);
const peerMetricRows={};
['P/E','EV/EBITDA','EV/EBIT','EV/Sales','P/S'].forEach((m,i)=>{const r=26+i,c=['AA','AB','AC','AD','AE'][i];peerMetricRows[m]=r;put('Peers',`C${r}`,m);form('Peers',`J${r}`,`=COUNT(${c}6:${c}20)`);
 ['MIN','MAX','AVERAGE','MEDIAN'].forEach((fn,j)=>form('Peers',`${col(3+j)}${r}`,`=IF(J${r}>0,${fn}(${c}6:${c}20),"n.a.")`));
 for(const [dest,q] of [['H',.25],['I',.75]])form('Peers',`${dest}${r}`,`=IF(J${r}>0,PERCENTILE(${c}6:${c}20,${q}),"n.a.")`);
});

title('Multiple policy','Multiple selection and adjustments','No default median or premium. Every selected anchor and adjustment requires an analyst rationale.');
block('Multiple policy','C5',[['Method','Case','Anchor','Manual anchor','Growth adj.','Margin adj.','ROCE adj.','Leverage adj.','Quality adj.','Rationale','Anchor value','Selected multiple']]);
const policyRows={};
let policyRow=6;
for(const scenario of ['bear','base','bull'])for(const method of Object.keys(peerMetricRows)){
 const r=policyRow++,pr=peerMetricRows[method];policyRows[`${scenario}:${method}`]=r;
 block('Multiple policy',`C${r}`,[[method,scenario]]);sheets['Multiple policy'].getRange(`E${r}:L${r}`).format={fill:amber,font:{color:blue}};
 sheets['Multiple policy'].getRange(`E${r}`).dataValidation={rule:{type:'list',values:['Manual','Mean','Median','25th percentile','75th percentile']}};
 form('Multiple policy',`M${r}`,`=IF(E${r}="Manual",IF(ISNUMBER(F${r}),F${r},"n.a."),IF(E${r}="Mean",'Peers'!F${pr},IF(E${r}="Median",'Peers'!G${pr},IF(E${r}="25th percentile",'Peers'!H${pr},IF(E${r}="75th percentile",'Peers'!I${pr},"n.a.")))))`);
 form('Multiple policy',`N${r}`,ready([`M${r}`,`G${r}`,`H${r}`,`I${r}`,`J${r}`,`K${r}`],`M${r}*(1+SUM(G${r}:K${r}))`,`AND(L${r}<>"",M${r}>0,SUM(G${r}:K${r})>-1)`));
 sheets['Multiple policy'].getRange(`G${r}:K${r}`).setNumberFormat(pct);
}

title('Transactions','Precedent transaction evidence','Enter enterprise value separately from stake consideration. Normalize control, synergies and financial periods.');
block('Transactions','C5',[['Target','Buyer','Announcement date','Consideration','Stake acquired','Enterprise value','Revenue','EBITDA','EBIT','PAT','Type','Include','Rationale','Source','Review','EV/Revenue','EV/EBITDA','EV/EBIT','P/E']]);
for(let r=6;r<=20;r++){
 sheets.Transactions.getRange(`C${r}:Q${r}`).format={fill:amber,font:{color:blue}};
 for(const [c,den] of [['R','I'],['S','J'],['T','K']])form('Transactions',`${c}${r}`,ready([`H${r}`,`${den}${r}`],`H${r}/${den}${r}`,`AND(${den}${r}>0,N${r}="Yes",O${r}<>"",P${r}<>"",Q${r}="Reviewed")`));
 put('Transactions',`U${r}`,'n.a.');
}
put('Transactions','C24','Transaction P/E requires separate attributable equity value, not enterprise value.');
put('Transactions','C26','Selected multiples are explicit assumptions after transaction comparability review.');

title('Segments','Sum of the parts','Convert each segment to owned equity value before aggregating. Apply only unallocated claims at group level.');
block('Segments','C5',[['Segment','Value basis','Segment value','Ownership','Allocated cash','Non-operating assets','Allocated debt','Allocated NCI','Preferred','Source','Owned equity']]);
for(let r=6;r<=20;r++){
 sheets.Segments.getRange(`C${r}:L${r}`).format={fill:amber,font:{color:blue}};
 form('Segments',`M${r}`,`=IF(C${r}="","",IF(AND(COUNT(E${r}:F${r})=2,F${r}>=0,F${r}<=1,L${r}<>""),IF(D${r}="Equity",E${r}*F${r},IF(AND(D${r}="Enterprise",COUNT(G${r}:K${r})=5),(E${r}+G${r}+H${r}-I${r}-J${r}-K${r})*F${r},"n.a.")),"n.a."))`);
}
const segmentAdjust=['PV unallocated corporate costs','Unallocated cash','Unallocated non-operating assets','Unallocated debt','Unallocated minorities','Unallocated preferred','Other senior claims','Justified holding discount'];
segmentAdjust.forEach((label,i)=>{put('Segments',`C${25+i}`,label);inputCell('Segments',`E${25+i}`);inputCell('Segments',`G${25+i}`);});
put('Segments','G24','Source / rationale');put('Segments','C35','SOTP equity value');
form('Segments','E35',`=IF(AND(COUNT(M6:M20)>0,COUNT(M6:M20)=COUNTA(C6:C20),COUNT(E25:E32)=8,COUNTBLANK(G25:G32)=0,E32>=0,E32<1),(SUM(M6:M20)-E25+E26+E27-E28-E29-E30-E31)*(1-E32),"n.a.")`);
// Company-specific SOTP is a live three-case EBIT build. Disclosed operating
// segments are valued separately; the same group claims are deducted once.
if(input.segments?.length){
 title('Segments','Segment valuation','Reported EBIT and enterprise/equity values in plain INR. Segment growth and multiples are explicit analyst assumptions.');
 sheets.Segments.getRange('C5:N35').values=Array.from({length:31},()=>Array(12).fill(null));
 sheets.Segments.getRange('C5:N35').format={fill:'#FFFFFF',font:{color:'#000000'}};
 block('Segments','C5',[['Segment','Reported EBIT','Bear growth','Base growth','Bull growth','Bear EV/EBIT','Base EV/EBIT','Bull EV/EBIT','Bear EV','Base EV','Bull EV','Source / assumption rationale']]);
 input.segments.forEach((seg,i)=>{const r=6+i;block('Segments',`C${r}`,[[seg.name,seg.ebit,...seg.growth,...seg.multiples,null,null,null,seg.source]]);sheets.Segments.getRange(`D${r}:J${r}`).format={fill:amber,font:{color:blue}};
  for(const [dest,g,m] of [['K','E','H'],['L','F','I'],['M','G','J']])form('Segments',`${dest}${r}`,ready([`D${r}`,`${g}${r}`,`${m}${r}`],`D${r}*(1+${g}${r})*${m}${r}`,`AND(${g}${r}>-1,${m}${r}>0)`));
 });
 sheets.Segments.getRange('E6:G10').setNumberFormat(pct);sheets.Segments.getRange('E6:G10').format.font.italic=true;
 sheets.Segments.getRange('H6:J10').setNumberFormat('0.0"x"');
 sheets.Segments.getRange('C:C').format.columnWidth=32;sheets.Segments.getRange('D:D').format.columnWidth=22;
 sheets.Segments.getRange('E:J').format.columnWidth=15;sheets.Segments.getRange('K:M').format.columnWidth=25;
 sheets.Segments.getRange('N:N').format.columnWidth=60;sheets.Segments.getRange('N6:N10').format.wrapText=true;sheets.Segments.getRange('C6:N10').format.rowHeight=60;
 put('Segments','C24','Annual corporate costs');inputCell('Segments','D24',input.segment_corporate_cost);
 put('Segments','C26','PV corporate costs, zero growth');
 put('Segments','C28','Group equity after claims');
 for(const [i,scenario] of ['Bear','Base','Bull'].entries()){
  const dest=['K','L','M'][i];put('Segments',`${dest}25`,scenario);
  form('Segments',`${dest}26`,ready(['D24',`'${scenario}'!E35`],`D24/'${scenario}'!E35`,`'${scenario}'!E35>0`));
  form('Segments',`${dest}28`,ready([`${dest}26`,`'${scenario}'!E61`],`SUM(${dest}6:${dest}${5+input.segments.length})-${dest}26+'${scenario}'!E61`));
 }
 put('Segments','C30','Segment EBIT and base group claims are sourced. Growth, EBIT multiples and corporate cost capitalisation are analyst assumptions. No extra hotel operating value is added.');
 sheets.Segments.getRange('C30:M33').merge();sheets.Segments.getRange('C30:M33').format.wrapText=true;
}

title('NAV','Asset and net asset valuation','Use realizable or economically justified asset values; do not substitute book values without a rationale.');
block('NAV','C5',[['Asset','Value','Ownership','Source / rationale','Valuation date','Review','Owned value']]);
for(let r=6;r<=20;r++){sheets.NAV.getRange(`C${r}:H${r}`).format={fill:amber,font:{color:blue}};form('NAV',`I${r}`,`=IF(C${r}="","",IF(AND(COUNT(D${r}:E${r})=2,E${r}>=0,E${r}<=1,F${r}<>"",ISNUMBER(G${r}),H${r}="Reviewed"),D${r}*E${r},"n.a."))`);}
['Debt','Other liabilities','Disposal taxes','Realisation costs','Other senior claims'].forEach((label,i)=>{put('NAV',`C${25+i}`,label);inputCell('NAV',`E${25+i}`);inputCell('NAV',`G${25+i}`);});
put('NAV','C32','NAV equity value');form('NAV','E32',`=IF(AND(COUNT(I6:I20)>0,COUNT(I6:I20)=COUNTA(C6:C20),COUNT(E25:E29)=5,COUNTBLANK(G25:G29)=0),SUM(I6:I20)-SUM(E25:E29),"n.a.")`);

title('Methods','Method suitability and reconciliation','Suitability, input availability and analyst weights are separate decisions. No automatic average.');
block('Methods','C5',[['Method','Applicable','Importance','Reason','Proposed weight','Weight rationale']]);
input.methods.forEach((m,i)=>{const r=6+i;block('Methods',`C${r}`,[[m.method,m.applicable,m.importance,m.reason,m.weight,m.weight_rationale]]);sheets.Methods.getRange(`D${r}:H${r}`).format.font.color=blue;sheets.Methods.getRange(`F${r}:F${r}`).format.columnWidth=65;});
sheets.Methods.getRange('D6:D19').dataValidation={rule:{type:'list',values:['Yes','No','Conditional']}};
sheets.Methods.getRange('G6:G19').setNumberFormat(pct);
sheets.Methods.getRange('F6:F19').format.wrapText=true;
sheets.Methods.getRange('C6:H19').format.rowHeight=58;
put('Methods','C23','Weight rule');put('Methods','F23','Weights must sum to 100%. Excluded methods need explicit zero; each included weight needs a rationale.');

const labels={7:'Revenue growth',8:'Revenue',9:'Gross margin',10:'EBITDA',11:'D&A',12:'EBIT',13:'Operating tax',14:'NOPAT',15:'Capex',16:'Closing operating NWC',17:'Change in operating NWC',18:'FCFF',19:'Opening debt',20:'Net borrowing',21:'Closing debt',22:'Interest expense',23:'Non-operating income',24:'Attributable net income',25:'Opening diluted shares',26:'Change in shares',27:'Closing diluted shares',28:'EPS',29:'FCFE',30:'Dividends',31:'Opening book equity',32:'Equity issuance / repurchases',33:'Other changes in equity',34:'Closing book equity',35:'Cost of equity',36:'WACC',37:'FCFF discount factor',38:'Equity discount factor',39:'PV of FCFF',40:'PV of FCFE',41:'PV of dividends',42:'Residual income',43:'PV of residual income'};
const results={};
for(const scenario of ['bear','base','bull']){
 const s=scenario[0].toUpperCase()+scenario.slice(1);results[scenario]={};
 title(s,`${s} operating forecast and valuation`,'Plain INR and actual shares. End-year discounting. All financial estimates require source or judgement labels.');
 put(s,'C4','WACC override');inputCell(s,'E4');put(s,'F4','Terminal g override');inputCell(s,'H4');
 put(s,'K4','Reverse growth override');inputCell(s,'M4');put(s,'N4','Margin override');inputCell(s,'P4');
 put(s,'C5','Forecast period');for(let y=0;y<5;y++)form(s,`${col(4+y)}5`,`=IF(ISNUMBER(${actualDate}),EDATE(${actualDate},${12*(y+1)}),"Period required")`);
 sheets[s].getRange('E5:I5').setNumberFormat('dd-mmm-yyyy');
 for(const [r,l] of Object.entries(labels))put(s,`C${r}`,l);
 for(let y=0;y<5;y++){
  const c=col(4+y),p=col(3+y),D=id=>driver(id,scenario,y);
  form(s,`${c}7`,`=IF(ISNUMBER($M$4),$M$4,IF('Drivers'!$E$6="Volume and price/mix",IF(AND(ISNUMBER(${D('volume_growth')}),ISNUMBER(${D('price_mix_growth')})),(1+${D('volume_growth')})*(1+${D('price_mix_growth')})-1,"n.a."),IF(AND('Drivers'!$E$6="Direct disclosed drivers",'Drivers'!$E$12<>""),${D('direct_revenue_growth')},"n.a.")))`);
  const priorRev=y?`${p}8`:actual('revenue');form(s,`${c}8`,ready([priorRev,`${c}7`],`${priorRev}*(1+${c}7)`,`${c}7>-1`));
  form(s,`${c}9`,`=${D('gross_margin')}`);
  form(s,`${c}10`,`=IF(ISNUMBER(${c}8),IF(ISNUMBER($P$4),${c}8*$P$4,IF('Drivers'!$E$7="Cost bridge",IF(COUNT(${c}9,${D('advertising_ratio')},${D('employee_ratio')},${D('other_opex_ratio')})=4,${c}8*(${c}9-${D('advertising_ratio')}-${D('employee_ratio')}-${D('other_opex_ratio')}),"n.a."),IF(AND('Drivers'!$E$7="EBITDA margin",ISNUMBER(${D('ebitda_margin')})),${c}8*${D('ebitda_margin')},"n.a."))),"n.a.")`);
  for(const [r,id] of [[11,'da_ratio'],[15,'capex_ratio'],[16,'nwc_ratio']])form(s,`${c}${r}`,ready([`${c}8`,D(id)],`${c}8*${D(id)}`));
  form(s,`${c}12`,ready([`${c}10`,`${c}11`],`${c}10-${c}11`));
  form(s,`${c}13`,ready([`${c}12`,D('tax_rate')],`${c}12*${D('tax_rate')}`,`AND(${D('tax_rate')}>=0,${D('tax_rate')}<=1)`));
  form(s,`${c}14`,ready([`${c}12`,`${c}13`],`${c}12-${c}13`));
  const priorNwc=y?`${p}16`:actual('operating_nwc');form(s,`${c}17`,ready([`${c}16`,priorNwc],`${c}16-${priorNwc}`));
  form(s,`${c}18`,ready([`${c}14`,`${c}11`,`${c}15`,`${c}17`],`${c}14+${c}11-${c}15-${c}17`));
  link(s,`${c}19`,y?`${p}21`:actual('debt'));
  form(s,`${c}20`,`=${D('net_borrowing')}`);form(s,`${c}21`,ready([`${c}19`,`${c}20`],`${c}19+${c}20`,`${c}19+${c}20>=0`));
  form(s,`${c}22`,ready([`${c}19`,D('interest_rate')],`${c}19*${D('interest_rate')}`));
  form(s,`${c}23`,`=${D('nonoperating_income')}`);
  form(s,`${c}24`,ready([`${c}12`,`${c}22`,`${c}23`,D('tax_rate'),D('nci_profit')],`(${c}12-${c}22+${c}23)*(1-${D('tax_rate')})-${D('nci_profit')}`));
  link(s,`${c}25`,y?`${p}27`:`'Market'!D20`);form(s,`${c}26`,`=${D('shares_change')}`);
  form(s,`${c}27`,ready([`${c}25`,`${c}26`],`${c}25+${c}26`,`${c}25+${c}26>0`));
  form(s,`${c}28`,ready([`${c}24`,`${c}27`],`${c}24/${c}27`,`${c}27>0`));
  form(s,`${c}29`,ready([`${c}24`,`${c}11`,`${c}15`,`${c}17`,`${c}20`],`${c}24+${c}11-${c}15-${c}17+${c}20`));
  form(s,`${c}30`,ready([`${c}24`,D('dividend_payout')],`${c}24*${D('dividend_payout')}`,`AND(${c}24>=0,${D('dividend_payout')}>=0,${D('dividend_payout')}<=1)`));
  link(s,`${c}31`,y?`${p}34`:actual('book_equity'));form(s,`${c}32`,`=${D('equity_proceeds')}`);form(s,`${c}33`,`=${D('other_equity_changes')}`);
  form(s,`${c}34`,ready([`${c}31`,`${c}24`,`${c}30`,`${c}32`,`${c}33`],`${c}31+${c}24-${c}30+${c}32+${c}33`));
  form(s,`${c}35`,ready([D('risk_free_rate'),D('beta'),D('equity_risk_premium')],`${D('risk_free_rate')}+${D('beta')}*${D('equity_risk_premium')}`));
  form(s,`${c}36`,`=IF(ISNUMBER($E$4),$E$4,IF(AND(ISNUMBER(${c}35),ISNUMBER(${D('debt_weight')}),${D('debt_weight')}>=0,${D('debt_weight')}<=1),IF(${D('debt_weight')}=0,${c}35,IF(COUNT(${D('pretax_cost_debt')},${D('tax_rate')})=2,${c}35*(1-${D('debt_weight')})+${D('pretax_cost_debt')}*(1-${D('tax_rate')})*${D('debt_weight')},"n.a.")),"n.a."))`);
  const priorDcf=y?`${p}37`:'1',priorEq=y?`${p}38`:'1';
  const exponent=y?'1':'$E$82';
  form(s,`${c}37`,ready([`${c}36`,priorDcf,exponent],`${priorDcf}/(1+${c}36)^(${exponent})`,`${c}36>0`));form(s,`${c}38`,ready([`${c}35`,priorEq,exponent],`${priorEq}/(1+${c}35)^(${exponent})`,`${c}35>0`));
  for(const [r,cf,disc] of [[39,18,37],[40,29,38],[41,30,38]])form(s,`${c}${r}`,ready([`${c}${cf}`,`${c}${disc}`,exponent],`${c}${cf}*${c}${disc}*(${exponent})`));
  form(s,`${c}42`,ready([`${c}24`,`${c}31`,`${c}35`],`${c}24-${c}31*${c}35`));form(s,`${c}43`,ready([`${c}42`,`${c}38`],`${c}42*${c}38`));
 }
 for(const r of [7,9,35,36,37,38])sheets[s].getRange(`E${r}:I${r}`).setNumberFormat(pct);
 put(s,'C95','Operating EBITDA margin');for(const c of ['E','F','G','H','I'])form(s,`${c}95`,ready([`${c}10`,`${c}8`],`${c}10/${c}8`,`${c}8>0`));sheets[s].getRange('E95:I95').setNumberFormat(pct);
 band(s,45,'Terminal assumptions and equity bridge');
 const terminalLabels=['Terminal growth','Terminal ROIC','Terminal ROE','Terminal WACC','Terminal cost of equity','Terminal NOPAT','Terminal FCFF','Terminal enterprise value','PV terminal FCFF value','Terminal attributable income','Terminal FCFE','Terminal equity value','PV terminal FCFE value','PV terminal dividends','PV terminal residual income','Enterprise to equity adjustment','Dilution / equity issuance check'];
 terminalLabels.forEach((l,i)=>put(s,`C${46+i}`,l));
 form(s,'E46',`=IF(ISNUMBER($H$4),$H$4,${driver('terminal_growth',scenario)})`);form(s,'E47',`=${driver('terminal_roic',scenario)}`);form(s,'E48',`=${driver('terminal_roe',scenario)}`);link(s,'E49','I36');link(s,'E50','I35');
 sheets[s].getRange('E46:E50').setNumberFormat(pct);
 form(s,'E51',ready(['I12','E46',driver('tax_rate',scenario,4)],`I12*(1+E46)*(1-${driver('tax_rate',scenario,4)})`));
 form(s,'E52',ready(['E51','E46','E47'],'E51*(1-E46/E47)','AND(E47>E46,E46>=0,E47>0)'));
 form(s,'E53',ready(['E52','E49','E46'],'E52/(E49-E46)','AND(E49>E46,E52>0)'));
 form(s,'E54',ready(['E53','I37'],'E53*I37'));
 form(s,'E55',ready(['I24','E46'],'I24*(1+E46)'));
 form(s,'E56',ready(['E55','E46','E48'],'E55*(1-E46/E48)','AND(E48>E46,E46>=0,E55>0)'));
 form(s,'E57',ready(['E56','E50','E46'],'E56/(E50-E46)','E50>E46'));form(s,'E58',ready(['E57','I38'],'E57*I38'));
 link(s,'E59','E58');
 form(s,'E60',ready(['I34','E48','E50','E46','I38'],'I34*(E48-E50)/(E50-E46)*I38','AND(E50>E46,E48>E46)'));
 link(s,'E61','E87');
 form(s,'E62',`=IF(AND(COUNT(E26:I26)=5,COUNT(E32:I32)=5,SUMSQ(E26:I26)=0,SUMSQ(E32:I32)=0),"No forecast dilution","Missing or nonzero issuance: allocation required")`);
 band(s,64,'Valuation results');block(s,'C65',[['Method','Basis','Enterprise value','Equity value','Per share','Input status']]);
 input.methods.forEach((m,i)=>{const r=66+i;results[scenario][m.method]=r;put(s,`C${r}`,m.method);put(s,`D${r}`,['DCF FCFF','EV/EBITDA','EV/EBIT','EV/Sales','Precedent EV/Revenue','Precedent EV/EBITDA'].includes(m.method)?'Enterprise':'Equity');
  const allowed=`AND('Methods'!D${6+i}="Yes",$E$62="No forecast dilution")`;
  const evMethods={'EV/EBITDA':['ebitda','EV/EBITDA',10],'EV/EBIT':['ebit','EV/EBIT',12],'EV/Sales':['sales','EV/Sales',8]};
  if(m.method==='DCF FCFF')form(s,`E${r}`,ready(['E54',...['E','F','G','H','I'].map(c=>`${c}39`)],`SUM(E39:I39)+E54`,allowed));
  else if(evMethods[m.method]){let [key,policy,fr]=evMethods[m.method],manual=driver('selected_ev_'+key,scenario);const multiple=`IF(ISNUMBER(${manual}),${manual},'Multiple policy'!N${policyRows[`${scenario}:${policy}`]})`;form(s,`E${r}`,ready([`E${fr}`,multiple],`E${fr}*${multiple}`,`AND(${allowed},${multiple}>0,E${fr}>0)`));}
  else if(m.method.startsWith('Precedent')){const cf=m.method.endsWith('Revenue')?'selected_pta_revenue':'selected_pta_ebitda',fr=m.method.endsWith('Revenue')?8:10;form(s,`E${r}`,ready([`E${fr}`,driver(cf,scenario)],`E${fr}*${driver(cf,scenario)}`,`AND(${allowed},${driver(cf,scenario)}>0,E${fr}>0)`));}
  else put(s,`E${r}`,'n.a.');
  if(sheets[s].getRange(`D${r}`).values[0][0]==='Enterprise')form(s,`F${r}`,ready([`E${r}`,'E61'],`E${r}+E61`));
  else if(m.method==='FCFE')form(s,`F${r}`,ready(['E58',...['E','F','G','H','I'].map(c=>`${c}40`)],'SUM(E40:I40)+E58',allowed));
  else if(m.method==='DDM')form(s,`F${r}`,ready(['E59',...['E','F','G','H','I'].map(c=>`${c}41`)],'SUM(E41:I41)+E59',allowed));
  else if(m.method==='Residual income')form(s,`F${r}`,ready([actual('book_equity'),'E60',...['E','F','G','H','I'].map(c=>`${c}43`)],`${actual('book_equity')}+SUM(E43:I43)+E60`,`AND(${allowed},SUMSQ(E33:I33)=0,COUNT(E33:I33)=5)`));
  else if(m.method==='NAV')form(s,`F${r}`,ready(["'NAV'!E32"],"'NAV'!E32",`'Methods'!D${6+i}="Yes"`));
  else if(m.method==='SOTP'){const ref=input.segments?.length?`'Segments'!${{bear:'K',base:'L',bull:'M'}[scenario]}28`:"'Segments'!E35";form(s,`F${r}`,ready([ref],ref,`'Methods'!D${6+i}="Yes"`));}
  else if(['Forward P/E','P/S','PEG'].includes(m.method)){
   let multiple=m.method==='Forward P/E'?`IF(ISNUMBER(${driver('selected_pe',scenario)}),${driver('selected_pe',scenario)},'Multiple policy'!N${policyRows[`${scenario}:P/E`]})`:m.method==='P/S'?`IF(ISNUMBER(${driver('selected_ps',scenario)}),${driver('selected_ps',scenario)},'Multiple policy'!N${policyRows[`${scenario}:P/S`]})`:`${driver('selected_peg',scenario)}*${driver('eps_growth_horizon',scenario)}*100`;
   const metric=m.method==='P/S'?'E8':'E24';form(s,`F${r}`,ready([metric,multiple],`${metric}*(${multiple})`,`AND(${allowed},${metric}>0,(${multiple})>0)`));
  }else put(s,`F${r}`,'n.a.');
  form(s,`G${r}`,ready([`F${r}`,"'Market'!D20"],`F${r}/'Market'!D20`,`'Market'!D20>0`));
  form(s,`H${r}`,`=IF(ISNUMBER(G${r}),"Calculated scenario",IF('Methods'!D${6+i}="No","Not applicable","Missing inputs or suitability decision"))`);
 });
 sheets[s].getRange('G66:G79').setNumberFormat(price);
 band(s,80,'Valuation date and interim cash bridge');
 put(s,'C81','Valuation date');form(s,'E81',`=IF(ISNUMBER('Market'!D22),'Market'!D22,${actual('revenue').replace(/I\d+$/,'I6')})`);sheets[s].getRange('E81').setNumberFormat('dd-mmm-yyyy');
 put(s,'C82','Remaining first forecast-year fraction');form(s,'E82',ready(['E81','E5',actualDate],`(E5-E81)/(E5-${actualDate})`,`AND(E81>=${actualDate},E81<E5)`));sheets[s].getRange('E82').setNumberFormat(pct);
 put(s,'C84','Estimated interim FCFE since balance');form(s,'E84',`=IF(E82=1,0,${ready(['E29','E82'],'E29*(1-E82)').slice(1)})`);
 put(s,'C85','Assumed distributions / dividend claims');form(s,'E85',`=IF(ISNUMBER('Market'!D28),'Market'!D28,IF(E82=1,0,"n.a."))`);
 put(s,'C86','Estimated change to equity bridge');form(s,'E86',ready(['E84','E85'],'E84-E85'));
 put(s,'C87','Projected enterprise/equity adjustment');form(s,'E87',ready(["'Market'!D25",'E86'],"'Market'!D25+E86"));
 put(s,'C89','Interim approximation');put(s,'E89','Uniform first-year cash accrual and assumed dividend claims roll the old balance forward. This is an estimate, not a reported interim balance.');sheets[s].getRange('E89:J92').merge();sheets[s].getRange('E89:J92').format.wrapText=true;
 // Genuine native two-input sensitivities reference the actual model overrides.
 put(s,'K6','DCF WACC and terminal-growth sensitivity');
 form(s,'K8','=G66');
 for(let i=0;i<5;i++){
  const c=['L','M','N','O','P'][i];
  // Grid spacing is an analysis convention, not an economic assumption.
  form(s,`${c}8`,`=IF(ISNUMBER(K15),K15+${i-2}*1%,"n.a.")`);
  form(s,`K${9+i}`,`=IF(ISNUMBER(${driver('terminal_growth',scenario)}),${driver('terminal_growth',scenario)}+${i-2}*0.5%,"n.a.")`);
 }
 // Data Tables are installed after disposable fixture checks, avoiding repeated
 // full-model sensitivity recalculation while test inputs are being restored.
 sheets[s].getRange('L8:P8').setNumberFormat(pct);sheets[s].getRange('K9:K13').setNumberFormat(pct);sheets[s].getRange('L9:P13').setNumberFormat(price);
 // Anchor axes to the unmodified financing assumptions, never an override.
 form(s,'K15',ready([driver('risk_free_rate',scenario,4),driver('beta',scenario,4),driver('equity_risk_premium',scenario,4),driver('debt_weight',scenario,4)],`(${driver('risk_free_rate',scenario,4)}+${driver('beta',scenario,4)}*${driver('equity_risk_premium',scenario,4)})*(1-${driver('debt_weight',scenario,4)})+IF(${driver('debt_weight',scenario,4)}=0,0,${driver('pretax_cost_debt',scenario,4)}*(1-${driver('tax_rate',scenario,4)})*${driver('debt_weight',scenario,4)})`));
 sheets[s].getRange('K15').setNumberFormat(pct);
 put(s,'K16','Sensitivity grid spacing: WACC 1 pp; terminal growth 0.5 pp. Edit axes to change the range.');
 put(s,'K19','Market-implied P/E');form(s,'N19',ready(["'Market'!D7",'E28'],"'Market'!D7/E28",'E28>0'));
 put(s,'K20','Market-implied EV/EBITDA');form(s,'N20',ready(["'Market'!D24",'E10'],"'Market'!D24/E10",'E10>0'));
 put(s,'K21','EPS implied by selected P/E');form(s,'N21',ready(["'Market'!D7",driver('selected_pe',scenario)],`'Market'!D7/${driver('selected_pe',scenario)}`,`${driver('selected_pe',scenario)}>0`));
 put(s,'K24','Growth and margin combinations require an explicit fixed-assumption reverse solve.');
 put(s,'K25','One price cannot identify growth, margin and terminal growth uniquely.');
}

title('Dashboard',input.company+' valuation','Evidence date and financial basis must be established before interpreting a valuation range.');
if(input.case_as_of){put('Dashboard','C3','Conditional run as of '+input.market.valuation_date+'. Forecasts and capital costs are analyst estimates.');put('Dashboard','C4','No independently validated peer set: P/E and EV/EBITDA are multiple stress tests.');}
put('Dashboard','C5','Forecast reporting basis');put('Dashboard','F5',input.sources.length?input.sources.at(-1).accounting_scope+' / '+input.sources.at(-1).operations_scope:'Awaiting reviewed statements');
put('Dashboard','H5','Latest annual period');put('Dashboard','K5',input.periods.at(-1)||'Not available');
band('Dashboard',7,input.case_as_of?'Conditional valuation and multiple stress cases':'Valuation triangulation');
block('Dashboard','C8',[['Method','Bear per share','Base per share','Bull per share','Weight','Base result status']]);
const displayedMethods=input.methods.map((m,i)=>({m,i})).filter(({m})=>m.applicable!=='No'||m.weight);
displayedMethods.forEach(({m,i},j)=>{let r=9+j;put('Dashboard',`C${r}`,input.case_as_of&&['Forward P/E','EV/EBITDA'].includes(m.method)?m.method+' (stress)':m.method);
 for(const [c,scenario] of [['D','bear'],['E','base'],['F','bull']])link('Dashboard',`${c}${r}`,`'${scenario[0].toUpperCase()+scenario.slice(1)}'!G${results[scenario][m.method]}`);
 link('Dashboard',`G${r}`,`'Methods'!G${6+i}`);form('Dashboard',`H${r}`,`='Base'!H${results.base[m.method]}`);
});
sheets.Dashboard.getRange('D9:F22').setNumberFormat(price);sheets.Dashboard.getRange('G9:G22').setNumberFormat(pct);
sheets.Dashboard.getRange('D25:F25').setNumberFormat(price);
// Excluded method results remain formula-addressable for audit and future
// activation, but do not clutter the company's reader-facing valuation table.
const excluded=input.methods.filter(m=>m.applicable==='No' && !m.weight);
if(displayedMethods.length<14)sheets.Dashboard.getRange(`C${9+displayedMethods.length}:H22`).format.rowHeight=1;
put('Dashboard','C6',`Selected methods shown; ${excluded.length} excluded methods omitted from this view. See Methods for reasons.`);
// Blank historical facts are unavailable evidence, not invitations to insert
// arbitrary estimates. Keep editable forecast assumptions on Assumptions.
// Missing inputs are labelled where the compact input schedule is populated.
band('Dashboard',24,'Reconciled conditional scenario values');
put('Dashboard','C25','Weighted value per share');
block('Dashboard','C54',[['Weight calculation components','Bear','Base','Bull','Weight','Bear inputs','Base inputs','Bull inputs']]);
input.methods.forEach((m,i)=>{let r=55+i;put('Dashboard',`C${r}`,m.method);link('Dashboard',`G${r}`,`'Methods'!G${6+i}`);
 for(const [c,check,scenario] of [['D','H','bear'],['E','I','base'],['F','J','bull']]){const sheet=scenario[0].toUpperCase()+scenario.slice(1),ref=`'${sheet}'!G${results[scenario][m.method]}`;form('Dashboard',`${c}${r}`,`=IF(ISNUMBER(${ref}),${ref},0)`);form('Dashboard',`${check}${r}`,`=IF(ISNUMBER(G${r}),IF(G${r}=0,1,IF(AND(G${r}>0,ISNUMBER(${ref}),'Methods'!H${6+i}<>""),1,0)),0)`);}});
for(const [c,check] of [['D','H'],['E','I'],['F','J']])form('Dashboard',`${c}25`,`=IF(AND(COUNT(G55:G68)=14,ABS(SUM(G55:G68)-1)<0.0000001,SUM(${check}55:${check}68)=14),SUMPRODUCT(${c}55:${c}68,G55:G68),"n.a.")`);
put('Dashboard','C27','Current market price');link('Dashboard','E27',"'Market'!D7");
sheets.Dashboard.getRange('E27').setNumberFormat(price);
put('Dashboard','C29','Minimum calculated method');form('Dashboard','E29','=IF(COUNT(E9:E22)>0,MIN(E9:E22),"n.a.")');
put('Dashboard','C30','Maximum calculated method');form('Dashboard','E30','=IF(COUNT(E9:E22)>0,MAX(E9:E22),"n.a.")');
put('Dashboard','C32','DCF terminal value / enterprise value');form('Dashboard','E32',ready(["'Base'!E54","'Base'!E66"],"'Base'!E54/'Base'!E66","'Base'!E66>0"));sheets.Dashboard.getRange('E32').setNumberFormat(pct);
band('Dashboard',35,'Findings requiring investigation');
put('Dashboard','C36','Operating cash flow / attributable profit');form('Dashboard','F36',ready([actual('cfo'),actual('net_income')],`${actual('cfo')}/${actual('net_income')}`,`${actual('net_income')}>0`));
sheets.Dashboard.getRange('F36').setNumberFormat('0.00"x"');
put('Dashboard','C38','Valuation method spread');form('Dashboard','F38',ready(['E29','E30'],'E30/E29-1','E29>0'));sheets.Dashboard.getRange('F38').setNumberFormat(pct);
put('Dashboard','C40','Source and review status');put('Dashboard','F40',input.issues.join(' ')||'Inspect Sources and Checks before interpreting results.');sheets.Dashboard.getRange('F40:M43').merge();sheets.Dashboard.getRange('F40:M43').format.wrapText=true;
put('Dashboard','C45','Interpretation');put('Dashboard','F45','Scenario outputs depend on assumptions. Numerical divergence is an investigation prompt, not proof of mispricing or misconduct.');sheets.Dashboard.getRange('F45:M48').merge();sheets.Dashboard.getRange('F45:M48').format.wrapText=true;
if(input.research_report){
 const url=input.research_report.pdf_url;
 assert.match(url,/^http:\/\/127\.0\.0\.1:8000\/analysis-reports\/[a-f0-9]{32}\/pdf\?view=true$/);
 put('Dashboard','C50','Full research and sources');
 nativeLink('Dashboard','F50',url,'Open matching research PDF');
 nativeLink('Dashboard','F51','#Research!C2','Read research and evidence in this workbook');
 sheets.Dashboard.getRange('F50:M50').merge();sheets.Dashboard.getRange('F51:M51').merge();
 sheets.Dashboard.getRange('F50:F51').format.font.color=blue;
}


title('Checks','Financial and model review','Checks observe source and model results; operating calculations do not depend on this sheet.');
block('Checks','C5',[['Check','Result','Meaning']]);
const checks=[['Balance sheet reconciliation',ready([actual('assets'),actual('liabilities'),actual('book_equity'),actual('nci')],`${actual('assets')}-${actual('liabilities')}-${actual('book_equity')}-${actual('nci')}`),'Assets less liabilities, parent equity and minority equity. Expected difference zero.'],
 ['EBITDA less D&A less EBIT',ready([actual('ebitda'),actual('da'),actual('ebit')],`${actual('ebitda')}-${actual('da')}-${actual('ebit')}`),'Expected difference zero on the same reporting basis.'],
 ['Valuation weights','=IF(COUNT(\'Methods\'!G6:G19)=14,SUM(\'Methods\'!G6:G19)-1,"n.a.")','Expected difference zero; correlated methods are not independent evidence.'],
 ['Capital-cost spread',ready(["'Base'!E49","'Base'!E46"],"'Base'!E49-'Base'!E46"),'Must be positive for terminal FCFF value.'],
 ['Terminal dependence review',`=IF(COUNT('Dashboard'!E32,${driver('terminal_value_limit','base')})=2,IF('Dashboard'!E32>${driver('terminal_value_limit','base')},"Review terminal dependence","Within chosen threshold"),"Review threshold or DCF unavailable")`,'Threshold is an explicit analyst policy input.'],
 ['Clean surplus',`=IF(COUNT('Base'!E33:I33)=5,IF(SUMSQ('Base'!E33:I33)=0,"No other equity changes entered","Reconcile accounting changes before residual income"),"Missing equity-change assumptions")`,'Zero is an explicit input, not a default.']];
checks.forEach((x,i)=>{put('Checks',`C${6+i}`,x[0]);form('Checks',`D${6+i}`,x[1]);put('Checks',`E${6+i}`,x[2]);});
sheets.Checks.getRange('E:E').format.columnWidth=90;
sheets.Checks.getRange('D:D').format.columnWidth=52;sheets.Checks.getRange('C6:E11').format.rowHeight=38;sheets.Checks.getRange('D6:E11').format.wrapText=true;
sheets.Checks.getRange('D6:D8').setNumberFormat('0.00');sheets.Checks.getRange('D9').setNumberFormat(pct);sheets.Checks.getRange('D6:D11').format.font.color='#000000';
put('Checks','C12','Dispersion between methods / stress cases');form('Checks','D12',`=IF(COUNT('Dashboard'!F38,${driver('method_divergence_limit','base')})=2,IF('Dashboard'!F38>${driver('method_divergence_limit','base')},"Investigate large divergence","Within chosen dispersion threshold"),"Dispersion threshold unavailable")`);put('Checks','E12','Large divergence is not resolved by averaging. Market-anchored stress tests are not independent evidence.');
put('Checks','C13','Balance age at valuation date');form('Checks','D13',ready(["'Market'!D22","'Market'!D16"],"'Market'!D22-'Market'!D16"));put('Checks','E13','Days between the reported balance and valuation date. The interim roll-forward is estimated.');
sheets.Checks.getRange('C12:E13').format.rowHeight=38;sheets.Checks.getRange('D12:E13').format.wrapText=true;

if(input.research_notes?.length){
 title('Research',input.company+' research','Reported facts and analyst interpretations are identified separately. Research cutoff: '+input.case_as_of);
 block('Research','C5',[['Topic','Finding / model treatment','Evidence']]);
 sheets.Research.getRange('D:D').format.columnWidth=100;sheets.Research.getRange('E:E').format.columnWidth=72;
 input.research_notes.forEach((n,i)=>{
  const row=6+i;sheets.Research.getRange(`C${row}:E${row}`).values=[[n.topic,n.finding,n.source]];
  if(n.source_url){
   assert.match(n.source_url,/^http:\/\/127\.0\.0\.1:8000\/(analysis-reports\/[a-f0-9]{32}\/pdf\?view=true|documents\/\d+\/original#page=\d+)$/);
   nativeLink('Research',`E${row}`,n.source_url,n.source);
   sheets.Research.getRange(`E${row}`).format.font.color=blue;
  }
 });
 sheets.Research.getRange(`C6:E${6+input.research_notes.length}`).format.wrapText=true;
 input.research_notes.forEach((n,i)=>{sheets.Research.getRange(`C${6+i}:E${6+i}`).format.rowHeight=Math.min(409,Math.max(75,Math.ceil(n.finding.length/95)*15+15,Math.ceil(n.source.length/65)*15+15));});
}

title('Sources','Source and fact audit','Reported facts, external evidence, guidance and analyst estimates retain their own categories.');
block('Sources','C5',[['Metric','Period ended','Original source','File','Page / row','Statement / evidence date','Source type','Review','Recorded file SHA-256','Review explanation','Recorded quotation (excerpt)','Accounting / operations basis']]);
const auditRows=input.verification_audit?.items;
const sourceRows=auditRows?.length?auditRows.map(r=>({metric:r.metric,period_end:r.period_end,source_url:r.source.url,source_file:r.source.file,source_page:r.source.page,source_date:r.source.date,source_type:'historical',review_status:r.checks.review_type,source_sha256:r.source.sha256,review_note:r.checks.review_explanation,source_quote:r.source.quote,accounting_scope:r.accounting_scope,operations_scope:r.operations_scope})):input.sources;
sourceRows.forEach((r,i)=>{const row=6+i;block('Sources',`C${row}`,[[r.metric,new Date(r.period_end+'T00:00:00Z'),r.source_url,r.source_file,r.source_page,new Date(r.source_date+'T00:00:00Z'),r.source_type,r.review_status,r.source_sha256||'Not recorded',r.review_note||'No explanation recorded',r.source_quote?(r.source_quote.length>350?r.source_quote.slice(0,350)+' ... (open full verification register)':r.source_quote):'No quotation recorded',r.accounting_scope+' / '+r.operations_scope]]);sheets.Sources.getRange(`K${row}:N${row}`).format.wrapText=true;sheets.Sources.getRange(`C${row}:N${row}`).format.rowHeight=120;const register=input.research_report?.report_id?`http://127.0.0.1:8000/analysis-reports/${input.research_report.report_id}/verification/view`:`http://127.0.0.1:8000/verification/${input.company_id}`;nativeLinks.push({sheet:'Sources',cell:`M${row}`,url:register,label:sheets.Sources.getRange(`M${row}`).values[0][0]});});
sheets.Sources.getRange('K:K').format.columnWidth=35;sheets.Sources.getRange('L:M').format.columnWidth=65;sheets.Sources.getRange('N:N').format.columnWidth=30;
sheets.Sources.getRange('D6:D240').setNumberFormat('dd-mmm-yyyy');sheets.Sources.getRange('H6:H240').setNumberFormat('dd-mmm-yyyy');
title('Guide','Model conventions and next inputs');
const guide=[
 ['Purpose','Company-specific multi-method valuation with separate live Bear, Base and Bull forecasts.'],
 ['Source intake','Add original PDFs and reviewed normalized CSV records to your chosen source folder. No company data is invented.'],
 ['Amounts','Plain INR; shares are actual share counts. INR lakh/crore source amounts are converted once during import.'],
 ['Missing inputs','n.a. means a required input or suitability decision is missing. Zero must be explicit.'],
 ['Financial history','Annual flow periods are matched. Mixed scopes and conflicting reviewed values are blocked.'],
 ['Operating drivers','Select volume/price-mix or justified direct growth. Select a cost bridge or an explicit EBITDA margin.'],
 ['Assumptions','Each estimate needs a source category, source date, source and rationale. Edit blue cells. Year-specific assumptions feed the matching year.'],
 ['Scenario builds','Bear, Base and Bull are separate visible live builds. Editing one scenario does not change the others.'],
 ['DCF','End-year FCFF discounted at WACC. Terminal reinvestment is g / ROIC. Cash and senior claims enter the equity bridge once.'],
 ['FCFE and dividends','Equity cash flows use cost of equity. Stable growth requires sustainable terminal ROE and reinvestment. Method suitability is separate.'],
 ['Residual income','Beginning book equity incurs the equity charge. Other equity changes require clean-surplus reconciliation.'],
 ['Dilution','These modules block valuations with missing/nonzero forecast share issuance until allocation to current holders is modelled.'],
 ['SOTP','Segments convert enterprise values to owned equity before aggregation. Only unallocated claims are applied again at group level.'],
 ['Peer multiples','Normalize periods and valuation dates. Select an anchor explicitly. Growth, margin, ROCE, leverage and quality adjustments require rationale.'],
 ['Transactions','A stake consideration is not enterprise value. Use separate enterprise value, financial metrics, transaction type and comparability rationale.'],
 ['Weights','Enter reasoned weights; do not mechanically average methods. Set excluded methods to zero.'],
 ['Sensitivity','Native Excel two-input Data Tables drive the actual WACC and terminal-growth override cells. Enable automatic recalculation including Data Tables.'],
 ['Reverse valuation','Market-implied multiples and EPS are linked. A full conditional growth/margin root solve and top-five sensitivity ranking are not yet automated.'],
 ['Refresh','Unchanged inputs can reuse an intact generated workbook. Changed inputs create a new export; edited workbooks are preserved.'],
 ['Assumption instructions','The local API previews bounded instructions such as set base volume_growth to 5% for years 1-3. Applying edits to an already open workbook needs a connected Excel session.'],
 ['Research gaps','Online refresh adds dated news leads and, when available, search-grounded impact review. Unverified headlines do not change numeric assumptions. Peer and transaction evidence still need review.'],
 ['Verification','Authoring checks do not establish native Excel recalculation. Test input edits in desktop Excel before relying on a completed company model.']];
guide.forEach((r,i)=>block('Guide',`C${5+i*2}`,[[r[0],r[1]]]));sheets.Guide.getRange('D:D').format.columnWidth=125;sheets.Guide.getRange('C5:D48').format.wrapText=true;sheets.Guide.getRange('C5:D48').format.rowHeight=29;

// Final presentation and independent spreadsheet-engine checks.
for(const name of names){sheets[name].getRange('C5:O5').format={fill:ink,font:{color:'#FFFFFF',bold:true},rowHeight:28};}
sheets.Dashboard.getRange('H:H').format.columnWidth=48;sheets.Dashboard.getRange('D:F').format.columnWidth=19;
wb.recalculate();
console.log('Initial formulas calculated');
const scan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},summary:'Workbook formula errors'});
await fs.writeFile(path.join(out,'formula-scan.json'),scan.ndjson);
const verification={sheets:names.length,financialInputs:input.sources.length,nativeExcelVerified:false,
 fixtureChecks:[],limitations:input.limitations};
// Recalculate real formulas with a disposable synthetic fixture, then restore
// every input. No fixture company values are exported to the user workbook.
const original=[];const setTemp=(s,a,v)=>{original.push([s,a,sheets[s].getRange(a).values]);put(s,a,v);};
for(const metric of Object.keys(metricRows))setTemp('Financials',`${latestFinancialColumn}${metricRows[metric]}`,({revenue:1000,ebitda:200,da:20,ebit:180,net_income:135,cfo:140,capex:30,operating_nwc:100,debt:100,cash:20,nci:0,preferred:0,nonoperating_assets:0,book_equity:500,shares:10,dividends:54,interest:10,assets:800,liabilities:300,invested_capital:600})[metric]);
setTemp('Financials',`${latestFinancialColumn}6`,new Date('2026-03-31T00:00:00Z'));
for(const [a,v] of Object.entries({D6:new Date('2026-10-16T00:00:00Z'),D7:120,D8:10,D9:100,D10:20,D11:0,D12:0,D13:0,D14:'Synthetic fixture',D15:new Date('2026-10-16T00:00:00Z'),D16:new Date('2026-03-31T00:00:00Z'),D17:'consolidated',D18:'Consistent fixture lease policy',D19:'INR',D20:10}))setTemp('Market',a,v);
setTemp('Market','D22',new Date('2026-03-31T00:00:00Z'));setTemp('Market','D28',0);setTemp('Market','D29',0);
setTemp('Drivers','E6','Volume and price/mix');setTemp('Drivers','E7','EBITDA margin');
const fixture={volume_growth:.03,price_mix_growth:.02,ebitda_margin:.2,da_ratio:.02,tax_rate:.25,capex_ratio:.03,nwc_ratio:.1,net_borrowing:0,interest_rate:.1,nonoperating_income:0,nci_profit:0,shares_change:0,equity_proceeds:0,other_equity_changes:0,dividend_payout:.4,risk_free_rate:.05,beta:1,equity_risk_premium:.05,pretax_cost_debt:.08,debt_weight:0,terminal_growth:.03,terminal_roic:.15,terminal_roe:.15,selected_pe:20,selected_ev_ebitda:12,selected_ev_ebit:15,selected_ev_sales:3,selected_ps:2,selected_peg:1.5,eps_growth_horizon:.1,selected_pta_revenue:3,selected_pta_ebitda:12};
for(const [id,value] of Object.entries(fixture))for(const scenario of ['bear','base','bull']){const r=ar[id][scenario];for(const [c,v] of [['E','analyst_assumption'],['F','Synthetic fixture'],['G',new Date('2026-10-18T00:00:00Z')],['I','Synthetic fixture only; removed before export']])setTemp('Assumptions',`${c}${r}`,v);for(let y=0;y<5;y++)setTemp('Assumptions',`${col(10+y)}${r}`,value);}
for(let i=0;i<input.methods.length;i++)setTemp('Methods',`D${6+i}`,'Yes');
wb.recalculate();
console.log('Synthetic fixture calculated');
const num=(s,a)=>Number(sheets[s].getRange(a).values[0][0]);
assert.ok(Math.abs(num('Base','E8')-1050.6)<1e-7,'Multiplicative revenue build');
assert.ok(Math.abs(num('Base','E18')-126.265)<1e-7,'FCFF fixture');
assert.ok(Number.isFinite(num('Base','G66'))&&num('Base','G66')>0,'DCF per-share fixture');
assert.ok(Math.abs(num('Base','G68')-num('Base','E28')*20)<1e-7,'EPS times P/E is per-share value');
const before=num('Base','G66');setTemp('Assumptions',`K${ar.volume_growth.base}`,.10);wb.recalculate();assert.ok(num('Base','G66')>before,'Live assumption sensitivity');assert.ok(Math.abs(num('Bear','E8')-1050.6)<1e-7,'Separate case isolation');
verification.fixtureChecks=['Multiplicative volume/price revenue','FCFF hand calculation','DCF per-share output','EPS times P/E dimensions','Input-change recalculation','Scenario isolation'];
assert.ok(Math.abs(num('Base','E29')-(num('Base','E24')+num('Base','E11')-num('Base','E15')-num('Base','E17')))<1e-7,'FCFE bridge');
assert.ok(Math.abs(num('Base','E42')-(num('Base','E24')-500*.1))<1e-7,'Residual income beginning equity charge');
verification.fixtureChecks.push('FCFE hand calculation','Residual income equity charge');
for(let i=0;i<input.methods.length;i++){setTemp('Methods',`G${6+i}`,i===0?1:0);setTemp('Methods',`H${6+i}`,'Synthetic weighting test');}
for(const [a,v] of Object.entries({C6:'Fixture asset',D6:1000,E6:1,F6:'Fixture source',G6:new Date('2026-10-18T00:00:00Z'),H6:'Reviewed'}))setTemp('NAV',a,v);
for(let r=25;r<=29;r++){setTemp('NAV',`E${r}`,20);setTemp('NAV',`G${r}`,'Fixture source');}
if(!input.segments?.length){for(const [a,v] of Object.entries({C6:'Fixture segment',D6:'Enterprise',E6:1000,F6:.5,G6:20,H6:0,I6:100,J6:0,K6:0,L6:'Fixture source'}))setTemp('Segments',a,v);
for(let r=25;r<=32;r++){setTemp('Segments',`E${r}`,0);setTemp('Segments',`G${r}`,'Fixture source');}}
wb.recalculate();
assert.ok(Math.abs(num('Dashboard','E25')-num('Base','G66'))<1e-7,'Reasoned weighted reconciliation');
assert.equal(num('NAV','E32'),900,'NAV deducts all senior claims');
if(!input.segments?.length)assert.equal(num('Segments','E35'),460,'SOTP bridge precedes ownership adjustment');
verification.fixtureChecks.push('Weighted reconciliation','NAV liability bridge');
if(!input.segments?.length)verification.fixtureChecks.push('SOTP ownership and equity bridge');
setTemp('Market','D22',new Date('2026-10-16T00:00:00Z'));setTemp('Market','D28',20);wb.recalculate();
assert.ok(Math.abs(num('Base','E82')-166/365)<1e-8,'Stub cash-flow fraction');
assert.ok(Math.abs(num('Base','E61')-(-80+num('Base','E29')*(1-166/365)-20))<1e-7,'Interim equity bridge');
verification.fixtureChecks.push('Stub discount timing','Interim FCFE and distributions bridge');
for(const [s,a,value] of original.reverse())sheets[s].getRange(a).values=value;
wb.recalculate();
if(input.sources.length===0)assert.equal(sheets.Dashboard.getRange('E25').values[0][0],'n.a.','Empty financial library must not produce a valuation');
verification.scenarios=Object.fromEntries(['Bear','Base','Bull'].map(s=>[s,{dcfPerShare:sheets[s].getRange('G66').values[0][0],pePerShare:sheets[s].getRange('G68').values[0][0],evEbitdaPerShare:sheets[s].getRange('G69').values[0][0],yearOneRevenue:sheets[s].getRange('E8').values[0][0],yearOneEps:sheets[s].getRange('E28').values[0][0],wacc:sheets[s].getRange('E36').values[0][0],terminalGrowth:sheets[s].getRange('E46').values[0][0],equityBridge:sheets[s].getRange('E61').values[0][0]}]));
if(sheets['Sector comparison']){
 const s='Sector comparison',q=Math.max(20,Math.max(13,input.sector_comparison.rows.length+8)+7)+1,before=num(s,'F6'),source=sheets[s].getRange(`G${q}`).values;
 if(typeof source[0][0]==='number'){
  put(s,`G${q}`,source[0][0]+1);wb.recalculate();
  assert.ok(Math.abs(num(s,'F6')-before-1/num(s,`F${q}`))<1e-10,'Peer EBITDA input updates live margin');
  sheets[s].getRange(`G${q}`).values=source;wb.recalculate();
  assert.equal(num(s,'F6'),before,'Peer EBITDA source restored');
 }
 verification.fixtureChecks.push('Sector operating comparison live source sensitivity');
}
if(sheets['Peer valuation']){
 const s='Peer valuation',rows=input.peer_valuation.companies;
 for(const [i,row] of rows.entries()){
  const r=21+i,v=row.values,tax=v.tax/v.pbt;
  const adjusted=(v.pat-v.exceptional_credit*(1-tax)*row.owner_allocation-v.oneoff_tax_credit*row.owner_allocation)/1e7;
  assert.ok(Math.abs(num(s,`AB${r}`)-adjusted)<1e-6,'Independent normalised PAT check');
  if(row.subject)assert.equal(sheets[s].getRange(`D${r}`).values[0][0],'No','Subject cannot anchor its own valuation');
 }
 const i=rows.findIndex(x=>x.included),r=21+i;
 if(i>=0){const before=num(s,`AE${r}`),source=sheets[s].getRange(`F${r}`).values;
  put(s,`F${r}`,source[0][0]*1.1);wb.recalculate();
  assert.ok(Math.abs(num(s,`AE${r}`)-before*1.1)<1e-8,'Market cap changes peer P/E live');
  sheets[s].getRange(`F${r}`).values=source;wb.recalculate();assert.equal(num(s,`AE${r}`),before);
 }
 verification.fixtureChecks.push('Peer normalisation independent arithmetic','Subject excluded from peer anchors','Live peer market-cap sensitivity');
}
if(input.sources.length){
 for(const s of ['Bear','Base','Bull'])assert.ok(Number.isFinite(num(s,'G66'))&&num(s,'G66')>0,'Populated company DCF must calculate: '+s);
 block('Dashboard','K54',[['Case','DCF per share']]);
 ['Bear','Base','Bull'].forEach((s,i)=>{put('Dashboard',`K${55+i}`,s);link('Dashboard',`L${55+i}`,`'${s}'!G66`);});
 // Keep the chart's unit-conversion data beside its actual input schedule.
 // No historical helper table or empty-year date formulas belong on Dashboard.
 block('Financials','C41',[['Year','Comparable revenue (INR crore)']]);
 for(let y=0;y<displayedPeriods.length;y++){const c=financialColumn(displayedPeriods[y].index),r=42+y;form('Financials',`C${r}`,`=TEXT(${c}6,"yyyy")`);form('Financials',`D${r}`,`=${c}${metricRows.revenue}/10000000`);}
 const valueChart=sheets.Dashboard.charts.add('bar',sheets.Dashboard.getRange('K54:L57'));valueChart.title='Conditional DCF value per share';valueChart.setPosition('J8','Q24');valueChart.series.items[0].fill=teal;valueChart.yAxis={numberFormatCode:'"₹"#,##0',numberFormatSourceLinked:false};
 // Do not plot absent historical years as reported zero revenue.
 const revenueChart=sheets.Dashboard.charts.add('line',sheets.Financials.getRange(`C41:D${41+displayedPeriods.length}`));revenueChart.title='Comparable-basis revenue (INR crore)';revenueChart.setPosition('J26','Q38');revenueChart.series.items[0].line={fill:ink,style:'solid',width:2};revenueChart.yAxis={numberFormatCode:'#,##0',numberFormatSourceLinked:false};
 valueChart.titleTextStyle.fontSize=12;revenueChart.titleTextStyle.fontSize=12;
 verification.nativeCharts=2;
}
if(input.segments?.length){
 const equity=num('Segments','L28'),multiple=num('Segments','I6'),bear=num('Segments','K28');
 put('Segments','I6',multiple+1);wb.recalculate();
 assert.ok(Math.abs((num('Segments','L28')-equity)-num('Segments','D6')*(1+num('Segments','F6')))<1,'Live SOTP EBIT multiple sensitivity');
 assert.equal(num('Segments','K28'),bear,'SOTP scenario isolation');
 assert.ok(Math.abs(num('Base','G79')-num('Segments','L28')/num('Market','D20'))<1e-7,'SOTP output allocation to shares');
 put('Segments','I6',multiple);wb.recalculate();
 assert.ok(Math.abs(num('Segments','L28')-equity)<1,'Restore SOTP multiple');
 verification.fixtureChecks.push('Live segment multiple change','SOTP case isolation','SOTP per-share linkage');
}
// Company exports omit empty optional evidence modules. Keep the reusable
// template complete; a new export restores a module when reviewed data arrives.
// Replace only references into omitted empty modules, retaining live manual
// multiple anchors and all business/valuation formulas in the retained sheets.
if(input.case_as_of){
 const optional=[['Peers',input.peers],['Transactions',input.transactions],['NAV',input.assets],['Segments',input.segments]];
 const omit=optional.filter(([,rows])=>!rows?.length).map(([name])=>name);
 const before=Object.fromEntries(['Bear','Base','Bull'].map(s=>[s,sheets[s].getRange('G66:G79').values]));
 for(const name of names.filter(n=>!omit.includes(n))){const range=sheets[name].getUsedRange(),formulas=range.formulas;
  for(let r=0;r<formulas.length;r++)for(let c=0;c<(formulas[r]?.length||0);c++){const f=formulas[r][c];if(typeof f!=='string'||!f.startsWith('='))continue;
   let updated=f;for(const removed of omit)updated=updated.replace(new RegExp(`(?:'${removed}'|${removed})!\\$?[A-Z]+\\$?\\d+(?::\\$?[A-Z]+\\$?\\d+)?`,'g'),'"n.a."');
   if(updated!==f)range.getCell(r,c).formulas=[[updated]];
  }
 }
 for(const name of omit){sheets[name].delete();names.splice(names.indexOf(name),1);delete sheets[name];}
 put('Guide','C51','Company export');put('Guide','D51','Empty optional evidence modules omitted: '+omit.join(', ')+'. Excluded method reasons remain in Methods. Add reviewed evidence and generate a new workbook to activate these modules.');
 sheets.Guide.getRange('D51').format.wrapText=true;sheets.Guide.getRange('C51:D51').format.rowHeight=45;
 wb.recalculate();
 for(const s of ['Bear','Base','Bull'])assert.deepEqual(sheets[s].getRange('G66:G79').values,before[s],'Removing empty modules must preserve all valuation outputs: '+s);
 verification.omittedEmptyModules=omit;verification.sheets=names.length;
}
for(const name of ['Bear','Base','Bull'])sheets[name].dataTables.add('K8:P13',{rowInput:'E4',columnInput:'H4'});
console.log('Scenario checks passed; sensitivity tables installed');
wb.recalculate();
const finalScan=await wb.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME\\?|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:50},summary:'Final formula error scan'});
await fs.writeFile(path.join(out,'formula-scan.json'),finalScan.ndjson);
assert.ok(!finalScan.ndjson.includes('"kind":"match"'),'Workbook contains spreadsheet errors');
await fs.writeFile(path.join(out,'verification.json'),JSON.stringify(verification,null,2));
for(const name of names){if(args.includes('--focused-previews')&&!['Dashboard','Financials','Statement history','Sector comparison','Peer valuation'].includes(name))continue;const range=name==='Peer valuation'?'C2:K18':name==='Sector comparison'?'C2:J15':name==='Assumptions'?'C2:P15':name==='Guide'?'C2:D17':name==='Dashboard'?'C2:Q51':name==='Research'?'C2:E17':name==='Peers'?'C2:J12':name==='Multiple policy'?'C2:N13':name==='Transactions'?'C2:L12':name==='Sources'?'C2:J12':name==='Segments'&&input.segments?.length?'C2:N33':name==='Segments'?'C2:M12':name==='Checks'?'C2:E14':name==='NAV'?'C2:I12':name==='Statement history'?`C2:${col(2+input.historical_statements.periods.length)}33`:name==='Financials'?'C2:I38':name==='Market'?'C2:F25':name==='Methods'?'C2:H20':name==='Drivers'?'C2:H17':'C2:I20';
 const blob=await wb.render({sheetName:name,range,scale:1,format:'png'});await fs.writeFile(path.join(out,'preview-'+name.replaceAll(' ','-')+'.png'),new Uint8Array(await blob.arrayBuffer()));}
if(input.sources.length){for(const [label,sheetName,range] of [['Base-results','Base','C45:J95'],['Base-sensitivity','Base','K6:P23'],['Market-bridge','Market','C22:K40']]){const blob=await wb.render({sheetName,range,scale:1,format:'png'});await fs.writeFile(path.join(out,'preview-'+label+'.png'),new Uint8Array(await blob.arrayBuffer()));}}
if(input.research_report){
 for(const [label,range] of [['Research-report','C2:E11'],['Research-findings','C20:E26']]){
  const blob=await wb.render({sheetName:'Research',range,scale:1,format:'png'});
  await fs.writeFile(path.join(out,'preview-'+label+'.png'),new Uint8Array(await blob.arrayBuffer()));
 }
}
if(input.external_updates&&input.research_notes?.length){const start=6+input.research_notes.findIndex(n=>n.topic==='Online update coverage');const blob=await wb.render({sheetName:'Research',range:`C${start}:E${Math.min(start+5,input.research_notes.length+5)}`,scale:1,format:'png'});await fs.writeFile(path.join(out,'preview-Online-review.png'),new Uint8Array(await blob.arrayBuffer()));}
const xlsx=await SpreadsheetFile.exportXlsx(wb);await xlsx.save(path.join(out,'SignalAI_FMCG_Valuation.xlsx'));
if(nativeLinks.length)await fs.writeFile(path.join(out,'report-links.json'),JSON.stringify(nativeLinks));
console.log(JSON.stringify({status:'exported',sheets:names.length,fixtureChecks:verification.fixtureChecks,nativeExcelVerified:false}));
