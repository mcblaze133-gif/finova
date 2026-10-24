// Reported operating benchmarks. No valuation-peer approvals or multiples.
export function buildSectorComparison(input, {sheets,title,block,put,form,ready,nativeLink,ink,blue,pct}){
 if(!sheets['Sector comparison'])return;
 const s='Sector comparison',rows=input.sector_comparison.rows,notesStart=Math.max(13,rows.length+8),rawHeader=Math.max(20,notesStart+7),sourceHeader=rawHeader+rows.length+4;
 title(s,'Sector operating comparison','Reported group figures. Category, scope and earnings-normalisation differences remain.');
 block(s,'C5',[['Company','Period end','Sales growth','EBITDA margin','CFO / PAT','Capex / sales','Net debt / sales','Reporting basis']]);
 sheets[s].getRange('C5:J5').format={fill:ink,font:{color:'#FFFFFF',bold:true},wrapText:true,rowHeight:34};
 sheets[s].getRange('C:C').format.columnWidth=39;sheets[s].getRange('J:J').format.columnWidth=40;
 block(s,`C${rawHeader}`,[['Company','Period end','Reporting basis','Revenue','EBITDA','Parent PAT','CFO','Capex','Debt incl. leases','Cash','Prior revenue','Prior period end','Peer review']]);
 sheets[s].getRange(`C${rawHeader}:O${rawHeader}`).format={fill:ink,font:{color:'#FFFFFF',bold:true},wrapText:true,rowHeight:34};
 sheets[s].getRange('O:O').format.columnWidth=65;
 for(const [i,row] of rows.entries()){
  const r=6+i,q=rawHeader+1+i;
  block(s,`C${q}`,[[row.company,new Date(row.end+'T00:00:00Z'),row.scope,...['revenue','ebitda','net_income','cfo','capex','debt','cash','prior_revenue'].map(k=>typeof row.values[k]==='number'?row.values[k]/10000000:'Not verified'),row.prior_end?new Date(row.prior_end+'T00:00:00Z'):'Not comparable',row.reason]]);
  sheets[s].getRange(`F${q}:M${q}`).format.font.color=blue;
  form(s,`C${r}`,`=C${q}`);form(s,`D${r}`,`=D${q}`);form(s,`J${r}`,`=E${q}`);
  for(const [c,refs,body,guard] of [['E',[`F${q}`,`M${q}`],`F${q}/M${q}-1`,`M${q}>0`],['F',[`G${q}`,`F${q}`],`G${q}/F${q}`,`F${q}>0`],['G',[`I${q}`,`H${q}`],`I${q}/H${q}`,`H${q}>0`],['H',[`J${q}`,`F${q}`],`J${q}/F${q}`,`F${q}>0`],['I',[`K${q}`,`L${q}`,`F${q}`],`(K${q}-L${q})/F${q}`,`F${q}>0`]])form(s,`${c}${r}`,ready(refs,body,guard));
  sheets[s].getRange(`E${r}:I${r}`).format.horizontalAlignment='right';sheets[s].getRange(`E${r}:F${r}`).setNumberFormat(pct);sheets[s].getRange(`G${r}`).setNumberFormat('0.00"x"');sheets[s].getRange(`H${r}:I${r}`).setNumberFormat(pct);
  for(const cell of [`D${r}`,`D${q}`,`N${q}`])sheets[s].getRange(cell).setNumberFormat('dd-mmm-yyyy');
  sheets[s].getRange(`E${q}`).format.wrapText=true;sheets[s].getRange(`O${q}`).format.wrapText=true;sheets[s].getRange(`C${q}:O${q}`).format.rowHeight=60;
  sheets[s].getRange(`J${r}`).format.wrapText=true;sheets[s].getRange(`C${r}:J${r}`).format.rowHeight=34;
 }
 put(s,`C${notesStart}`,'Growth uses adjacent annual periods on the same reporting basis. Missing inputs remain n.a.');
 put(s,`C${notesStart+1}`,'CFO / PAT tests cash backing. Net debt / sales compares financing exposure. EBITDA definitions can differ.');
 put(s,`C${notesStart+2}`,'These benchmarks do not justify a target multiple. ITC needs segment comparisons.');
 put(s,`C${notesStart+3}`,'Edited source inputs are analyst overrides; the original review does not verify an edited value.');
 put(s,`C${rawHeader-2}`,'Source inputs (INR crore). Editable values recalculate the comparison above.');
 block(s,`C${sourceHeader}`,[['Company','Metric','Source page','Review']]);
 sheets[s].getRange(`C${sourceHeader}:F${sourceHeader}`).format={fill:ink,font:{color:'#FFFFFF',bold:true}};
 sheets[s].getRange('E:E').format.columnWidth=24;
 let sourceRow=sourceHeader+1;
 for(const row of rows)for(const [metric,refs] of Object.entries(row.sources))for(const ref of refs){
  const r=sourceRow++;put(s,`C${r}`,row.company);put(s,`D${r}`,metric);nativeLink(s,`E${r}`,'http://127.0.0.1:8000'+ref.url,'Original p. '+(ref.pages||'?'));put(s,`F${r}`,'Recorded source review; not independent issuer authentication');sheets[s].getRange(`F${r}:J${r}`).merge();
 }
}
