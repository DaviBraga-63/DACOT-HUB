import { Bike, Boxes, ChefHat, ClipboardList, Landmark, Package, Users } from "lucide-react";

const MODULE_ICONS = {
  "clipboard-list": ClipboardList,
  "chef-hat": ChefHat,
  users: Users,
  boxes: Boxes,
  landmark: Landmark,
  bike: Bike,
};

export const getModuleIcon = (icon) => MODULE_ICONS[icon] || Package;
