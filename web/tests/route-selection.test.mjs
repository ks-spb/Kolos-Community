/** Decision boundaries complement full Python/JS tick parity tests. */
import test from 'node:test';
import assert from 'node:assert/strict';
import {certifiedChoice} from '../states/route-selection.mjs';

test('early threshold crossing waits for the alternative, including a small final lead',()=>{
 const rows=[{id:'fast',a:.56,upper:.65,allowed:true},{id:'detour',a:.35,upper:.68,allowed:true}];
 assert.deepEqual(certifiedChoice(rows,.55,false),{});
 rows[1].a=.66;assert.equal(certifiedChoice(rows,.55,false).winner.id,'detour');
});
test('empty, zero, ties, threshold equality and unavailable contenders are safe',()=>{
 assert.deepEqual(certifiedChoice([],.55,true),{blocked:true});
 assert.deepEqual(certifiedChoice([{a:0,upper:0,allowed:true}],.55,true),{blocked:true});
 const tied=['b','a'].map(id=>({id,a:.7,upper:.7,allowed:true}));
 for(const rows of [tied,[...tied].reverse()]){
  assert.deepEqual(certifiedChoice(rows,.55,false),{});
  assert.deepEqual(certifiedChoice(rows,.55,true),{ambiguous:true});
 }
 const edge=[{id:'only',a:.55,upper:.55,allowed:true},{a:1,upper:1,allowed:false}];
 assert.equal(certifiedChoice(edge,.55,false).winner.id,'only');
 edge[0].a=.549999999;assert.deepEqual(certifiedChoice(edge,.55,true),{blocked:true});
});
