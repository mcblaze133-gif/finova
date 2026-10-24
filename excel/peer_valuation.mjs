// All monetary source inputs are plain INR; presentation/build uses INR crore.
export function buildPeerValuation(input,{sheets,title,put,block,form,nativeLink,ink,blue,pct,ready}){
 const data=input.peer_valuation;if(!data)return;
 const s='Peer valuation',ws=sheets[s],rows=data.companies,n=rows.length;
 title(s,'Peer valuation cross-check',`Market close ${data.price_date}. ${data.earnings_period}. Analyst-adjusted earnings are estimates.`);
 block(s,'C5',[['Method','Low','Midpoint','High','Basis']]);
 ws.getRange('C:C').format.columnWidth=33;ws.getRange('G:G').format.columnWidth=55;
 const header=20,first=21,last=20+n,subject=first+rows.findIndex(r=>r.subject);
 const fields=['market_cap','price','shares','revenue','ebitda','da','pat','pbt','tax','group_pat','exceptional_credit','oneoff_tax_credit','ebitda_addback','debt','cash','nci','preferred','other_claims','nonoperating_assets'];
 block(s,'C20',[['Company','Selected peer','Business / scope',...fields.map(f=>f.replaceAll('_',' ')),'Tax proxy','Owner share','Adjusted EBITDA','Adjusted PAT','Book-bridge EV','P/E reported','P/E adjusted','EV/EBITDA','EV/EBIT','EV/Sales','P/S','Margin','Review']]);
 for(const [i,row] of rows.entries()){
  const r=first+i;
  block(s,`C${r}`,[[row.company,row.included?'Yes':'No',row.category,...fields.map(k=>row.values[k]===null||row.values[k]===undefined?'Not established':row.values[k]/(k==='price'||k==='shares'?1:1e7))]]);
  if(row.values.ebitda===null){
   put(s,`AL${r}`,row.values.finance_cost/1e7);put(s,`AM${r}`,row.values.other_income/1e7);
   form(s,`J${r}`,ready([`M${r}`,`P${r}`,`AL${r}`,`K${r}`,`AM${r}`],`M${r}-P${r}+AL${r}+K${r}-AM${r}`));
  }
  ws.getRange(`F${r}:X${r}`).format.font.color=blue;
  // Y/Z are explicit analyst proxies, not factual tax/ownership allocations.
  form(s,`Y${r}`,ready([`N${r}`,`M${r}`],`N${r}/M${r}`,`AND(M${r}>0,N${r}>=0,N${r}<M${r})`));
  put(s,`Z${r}`,row.owner_allocation);ws.getRange(`Z${r}`).format.font.color=blue;
  form(s,`AA${r}`,ready([`J${r}`,`R${r}`],`J${r}+R${r}`));
  form(s,`AB${r}`,ready([`L${r}`,`P${r}`,`Q${r}`,`Y${r}`,`Z${r}`],`L${r}-P${r}*(1-Y${r})*Z${r}-Q${r}*Z${r}`,`AND(Y${r}>=0,Y${r}<1,Z${r}>=0,Z${r}<=1)`));
  form(s,`AC${r}`,ready([`F${r}`,`S${r}`,`T${r}`,`U${r}`,`V${r}`,`W${r}`,`X${r}`],`F${r}+S${r}+U${r}+V${r}+W${r}-T${r}-X${r}`));
  for(const [c,refs,body,guard] of [['AD',[`F${r}`,`L${r}`],`F${r}/L${r}`,`L${r}>0`],['AE',[`F${r}`,`AB${r}`],`F${r}/AB${r}`,`AB${r}>0`],['AF',[`AC${r}`,`AA${r}`],`AC${r}/AA${r}`,`AND(AA${r}>0,AC${r}>0)`],['AG',[`AC${r}`,`AA${r}`,`K${r}`],`AC${r}/(AA${r}-K${r})`,`AND(AA${r}>K${r},AC${r}>0)`],['AH',[`AC${r}`,`I${r}`],`AC${r}/I${r}`,`AND(I${r}>0,AC${r}>0)`],['AI',[`F${r}`,`I${r}`],`F${r}/I${r}`,`I${r}>0`],['AJ',[`AA${r}`,`I${r}`],`AA${r}/I${r}`,`I${r}>0`]])form(s,`${c}${r}`,ready(refs,body,guard));
  put(s,`AK${r}`,row.normalisation_note+' '+row.selection_reason+' Bridge date '+row.balance_date+'.');
  ws.getRange(`F${r}:AJ${r}`).setNumberFormat('#,##0.00;(#,##0.00);"-"');ws.getRange(`Y${r}:Z${r}`).setNumberFormat(pct);ws.getRange(`AJ${r}`).setNumberFormat(pct);
 }
 put(s,'AL20','Finance cost');put(s,'AM20','Other income');
 // Included peer multiples only; subject and excluded companies cannot set anchors.
 let selected=first+n+4;
 block(s,`C${selected}`,[['Included company','Adjusted P/E','EV/EBITDA','EV/EBIT','EV/Sales','P/S']]);
 rows.forEach((row,i)=>{const q=first+i,r=selected+1+i;form(s,`C${r}`,`=C${q}`);for(const [dest,origin] of [['D','AE'],['E','AF'],['F','AG'],['G','AH'],['H','AI']])form(s,`${dest}${r}`,`=IF(D${q}="Yes",${origin}${q},"Excluded")`);});
 const a=selected+1,b=selected+n;
 block(s,'C10',[['Anchor','Low','Range midpoint','High','Usable peers','Mean','Median','25th percentile','75th percentile']]);
 for(const [r,column,label] of [[11,'D','Adjusted FY26 P/E'],[12,'E','FY26 EV/EBITDA'],[13,'F','FY26 EV/EBIT'],[14,'G','FY26 EV/Sales'],[15,'H','FY26 P/S']]){
  for(const [dest,fn] of [['H','AVERAGE'],['I','MEDIAN'],['J','PERCENTILE.INC'],['K','PERCENTILE.INC']])form(s,`${dest}${r}`,`=IF(COUNT(${column}${a}:${column}${b})>=2,${fn}(${column}${a}:${column}${b}${dest==='J'?',0.25':dest==='K'?',0.75':''}),"n.a.")`);
  put(s,`C${r}`,label);form(s,`G${r}`,`=COUNT(${column}${a}:${column}${b})`);
  form(s,`D${r}`,`=IF(G${r}>=2,MIN(${column}${a}:${column}${b}),"n.a.")`);
  form(s,`F${r}`,`=IF(G${r}>=2,MAX(${column}${a}:${column}${b}),"n.a.")`);
  form(s,`E${r}`,ready([`D${r}`,`F${r}`],`(D${r}+F${r})/2`));
 }
 put(s,'C6','Peer P/E value / share');put(s,'C7','Peer EV/EBITDA value / share');
 for(const [dest,anchor] of [['D','D'],['E','E'],['F','F']]){
  form(s,`${dest}6`,ready([`${anchor}11`,`AB${subject}`,`H${subject}`],`${anchor}11*AB${subject}*10000000/H${subject}`,`AND(AB${subject}>0,H${subject}>0)`));
  form(s,`${dest}7`,ready([`${anchor}12`,`AA${subject}`,`F${subject}`,`AC${subject}`,`H${subject}`],`(${anchor}12*AA${subject}-(AC${subject}-F${subject}))*10000000/H${subject}`,`AND(AA${subject}>0,H${subject}>0)`));
 }
 put(s,'G6','Historical FY26 earnings, not a forward EPS multiple. Tax effects are estimated.');put(s,'G7','FY26 operating earnings and dated book claims. Current enterprise value may differ.');
 put(s,'C17',data.policy.rationale);ws.getRange('C17:K18').merge();ws.getRange('C17').format.wrapText=true;
 put(s,'C19','Sources and company selection below. Blue source/analyst inputs are editable. No automatic weight in the main valuation.');
 const sourceStart=selected+n+5;let q=sourceStart;
 block(s,`C${q++}`,[['Company','Source','Recorded quotation / review']]);
 for(const row of rows){put(s,`C${q}`,row.company);put(s,`D${q}`,'Selection');put(s,`E${q++}`,row.selection_reason);for(const ref of row.sources){put(s,`C${q}`,row.company);nativeLink(s,`D${q}`,'http://127.0.0.1:8000'+ref.url,ref.title);put(s,`E${q}`,ref.quote.slice(0,350).replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g,' '));ws.getRange(`E${q}:K${q}`).merge();ws.getRange(`E${q}:K${q}`).format={wrapText:true,rowHeight:65};q++;}}
 ws.getRange(`C20:AK${last}`).format.rowHeight=44;ws.getRange(`C20:AK20`).format={fill:ink,font:{color:'#FFFFFF',bold:true},wrapText:true,rowHeight:60};
 ws.getRange('E:E').format.columnWidth=30;ws.getRange('AK:AK').format.columnWidth=95;ws.getRange(`AK21:AK${last}`).format.wrapText=true;
 ws.getRange('G11:G15').setNumberFormat('0');ws.getRange('D6:F7').setNumberFormat('"₹"#,##0.00');ws.getRange('D11:F15').setNumberFormat('0.00"x"');
 for(const r of [5,10,selected,sourceStart])ws.getRange(`C${r}:K${r}`).format={fill:ink,font:{color:'#FFFFFF',bold:true},rowHeight:30};
}
