import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { ArtifactReader, DescriptionView } from "./ArtifactReader";

describe("节目简介标签", () => {
  it("只在有简介时追加到四个产物之后", () => {
    Object.assign(globalThis, { location: { hash: "" } });
    const load = async () => "";
    const withDescription = renderToStaticMarkup(<ArtifactReader load={load} description="完整简介" />);
    const withoutDescription = renderToStaticMarkup(<ArtifactReader load={load} />);
    expect(withDescription.indexOf("逐字稿")).toBeLessThan(withDescription.indexOf("节目简介"));
    expect(withoutDescription).not.toContain("节目简介");
  });

  it("把简介当作纯文本渲染", () => {
    const html = renderToStaticMarkup(<DescriptionView text={'<img src=x onerror="alert(1)">\n第二行'} />);
    expect(html).toContain("&lt;img");
    expect(html).not.toContain("<img");
    expect(html).toContain("第二行");
  });
});
