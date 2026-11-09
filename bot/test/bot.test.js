import assert from "node:assert/strict";
import test from "node:test";
import { normalizeUrl } from "../src/validation.js";
import { awaitingCard, awaitingListCard, completionCard, episodeForm, subscriptionForm, subscriptionsCard, helpCard } from "../src/cards.js";

const id = "a".repeat(24);
test("完成推送标题包含播客名称和累计分钟秒时长", () => {
  for (const [duration, expected] of [[4105, "68:25"], [3600, "60:00"], [65, "1:05"], [5, "0:05"], ["4105", "68:25"]]) {
    const card = completionCard({ id, episode: { podcast_title: "测试播客", title: "单集标题", duration } });
    assert.equal(card.header.title.content, `测试播客 · 单集标题 (${expected})`);
  }
});

test("完成推送缺少元数据时保留标题且省略无效时长", () => {
  for (const duration of [undefined, null, "", 0, -1, "unknown", Infinity]) {
    assert.equal(completionCard({ id, episode: { title: "单集标题", duration } }).header.title.content, "单集标题");
  }
  assert.equal(completionCard({ id, filename: "audio.mp3" }).header.title.content, "audio.mp3");
  assert.equal(completionCard({ id }).header.title.content, "播客处理完成");
});

test("链接类型必须与卡片相符", () => {
  assert.equal(normalizeUrl(`https://xiaoyuzhoufm.com/episode/${id}?from=share`, "episode"), `https://www.xiaoyuzhoufm.com/episode/${id}`);
  assert.throws(() => normalizeUrl(`https://www.xiaoyuzhoufm.com/podcast/${id}`, "episode"), /单集链接/);
  assert.throws(() => normalizeUrl(`https://www.xiaoyuzhoufm.com/episode/${id}`, "podcast"), /播客主页链接/);
  assert.throws(() => normalizeUrl(`http://www.xiaoyuzhoufm.com/episode/${id}`, "episode"), /HTTPS/);
});

test("帮助和两种表单均提供所需动作", () => {
  assert.equal(helpCard().schema, "2.0");
  assert.deepEqual(Object.keys(helpCard().header.title).sort(), ["content", "tag"]);
  assert.equal(episodeForm().body.elements[0].elements.find((x) => x.name === "backend").initial_option, "qwen");
  assert.deepEqual(subscriptionForm().body.elements[0].elements.find((x) => x.name === "initial_backfill").options.map((x) => x.value), ["0", "1", "3"]);
  for (const form of [episodeForm(), subscriptionForm()]) {
    const elements = form.body.elements[0].elements;
    for (const select of elements.filter((element) => element.tag === "select_static")) {
      assert.equal(Object.hasOwn(select, "label"), false);
    }
    assert.equal(elements.at(-1).form_action_type, "submit");
    assert.equal(elements.at(-1).text.content, "确定");
  }
});

const callbacks = (card) => card.body.elements
  .flatMap((element) => element.behaviors || [])
  .filter((behavior) => behavior.type === "callback")
  .map((behavior) => behavior.value);

test("待确认单集推送包含简介和转写、忽略按钮", () => {
  const episode = { id: 7, podcast_title: "跨国串门儿计划", title: "#817", duration: 4105, description: "x".repeat(700), episode_url: `https://www.xiaoyuzhoufm.com/episode/${id}` };
  const card = awaitingCard(episode);
  assert.equal(card.header.title.content, "待确认：跨国串门儿计划 · #817 (68:25)");
  assert.equal(card.body.elements[0].content.length, 601);
  assert.deepEqual(callbacks(card), [{ action: "transcribe_episode", id: 7 }, { action: "dismiss_episode", id: 7 }]);
  assert.equal(awaitingCard({ ...episode, description: "" }).body.elements[0].content, "这一集没有简介。");
  assert.equal(awaitingListCard([]).body.elements[0].content, "没有待确认的单集");
  assert.equal(callbacks(awaitingListCard([episode, { ...episode, id: 8 }])).length, 4);
});

test("订阅管理可切换处理方式并查看待确认", () => {
  const card = subscriptionsCard([
    { id: 1, title: "手动", enabled: true, auto_process: false, awaiting_count: 2 },
    { id: 2, title: "自动", enabled: true, auto_process: true, awaiting_count: 0 },
  ]);
  const actions = callbacks(card);
  assert.deepEqual(actions.filter((value) => value.action === "set_auto_process"), [
    { action: "set_auto_process", id: 1, auto_process: true },
    { action: "set_auto_process", id: 2, auto_process: false },
  ]);
  assert.deepEqual(actions.filter((value) => value.action === "awaiting"), [{ action: "awaiting", id: 1 }]);
  assert.match(card.body.elements[0].content, /手动确认.*待确认 2/);
  assert.deepEqual(subscriptionForm().body.elements[0].elements.find((x) => x.name === "auto_process").options.map((x) => x.value), ["auto", "manual"]);
  assert.ok(callbacks(helpCard()).some((value) => value.action === "awaiting"));
});
