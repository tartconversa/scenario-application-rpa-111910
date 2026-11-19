# 共创申请门户协议

页面 / 身份固定为技术方资料员。技术方字段是title、scopes、data_use、notice、mode；场景方字段owner、condition只能观察，不能由技术方覆盖。院内hospital触发data_use和材料data，公共public触发notice和材料points，两者共享shared材料。草稿可不完整，正式受理需当前修订下字段材料齐全与场景方确认。
保存携页面修订，旧修订写入409 revision_conflict。保存改变技术字段会产生新修订并使之前确认不适用；场景方编辑也递增修订。只变更材料不改变技术范围时保留确认修订。/history是草稿、受理和修订历史，申请号APP-001保持稳定。
本地控制scenario_edit更改另一会话的条件；confirm表示场景方本人确认当前修订；dictionary更改显示名称并淘汰pilot枚举，新字典允许trial/production；correction登记对notice的定向补正；lose_reply令下次保存写入后返回503。演练控制仅供检查人员，技术方RPA不能借此代确认。

本地来源控制通过 POST /__control 发送JSON，例如 {"event":"reset"} 可重置样本。控制切换只影响合成来源，不能用来替业务处理方决定批准、签发或确认。来源服务与自动化客户端分别承担各自责任。
