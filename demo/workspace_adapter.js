// 用本地合成场景替代实时状态接口；所有原显示函数接收相同的数据结构。
function applyScenario(){
 const scenario=$('scenario').value,s=structuredClone(BASE_SNAPSHOT);
 const row=id=>s.checklist.find(item=>item.id===id);
 if(scenario==='stale'){
  s.management.status='WAIT_DATA';s.management.detail='示例异常：两腿行情已过期，等待完整数据。';
  row('summary_quotes').status='failed';row('summary_quotes').issue_ids=['quote_age'];
 }
 if(scenario==='mismatch'){
  s.mode='HALTED';s.management.status='STOPPED';s.management.label='持仓待核对';
  s.management.detail='示例异常：实际净腿与账本不一致，管理暂停。';
  s.verification.positions.passed=false;row('positions').status='failed';
 }
 if(scenario==='pending'){
  s.mode='OPEN_PENDING';s.management.status='ORDER_PENDING';
  s.management.detail='示例状态：已有部分成交，尚未完成订单及费用核对。';
  s.order_progress[0].trade_details.final=false;s.order_progress[0].filled=1;
  s.order_progress[0].label='部分成交，等待核对';s.order_progress[0].fees_ready=false;
  s.order_progress[0].trade_details.working_remaining=1;
  s.order_progress[0].trade_details.gross_cash=90;
  s.order_progress[0].trade_details.total_fees=null;
  s.order_progress[0].trade_details.net_cash=null;
  s.order_progress[0].legs.forEach(leg=>{leg.filled=leg.quantity/2;});
  row('inflight').status='pending';
 }
 s.check_summary=s.checklist;
 renderStatus(s);
 $('management-label').textContent='演示 · '+$('management-label').textContent;
 $('updated').textContent+='（固定示例，非实时）';
}
for(const name of ['history']){$(name+'-toggle').ontoggle=()=>{$(name+'-panel').hidden=!$(name+'-toggle').open;};}
$('calendar-view').onclick=event=>{const button=event.target.closest('[data-calendar-step]');if(button)moveCalendarMonth(Number(button.dataset.calendarStep));};
$('notice-dismiss').onclick=clearNotice;
$('scenario').onchange=applyScenario;
$('refresh').onclick=applyScenario;
applyScenario();
