import assert from "node:assert/strict";
import test from "node:test";
import { normalizeUrl } from "../src/validation.js";
import { episodeForm, subscriptionForm, helpCard } from "../src/cards.js";

const id = "a".repeat(24);
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
